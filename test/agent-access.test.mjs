import assert from 'node:assert/strict'
import test from 'node:test'
import {
  BUILT_IN_AGENT_ACCESS,
  MESSAGE_MARKS,
  accessCategory,
  authorRole,
  commandAuthority,
  legacyEnrollment,
  markNames,
  messageMarks,
  normalizeConnectorAgentSettings,
  normalizeConversationAgentSettings,
  resolveAgentAccess,
} from '../cloudflare-worker/worker/agent-access.js'

test('conversation categories follow type and group-assistant placement', () => {
  assert.equal(accessCategory('direct', 'folded'), 'direct')
  assert.equal(accessCategory('group', 'normal'), 'group')
  assert.equal(accessCategory('group', 'unknown'), 'group')
  assert.equal(accessCategory('group', 'folded'), 'group_assistant')
  assert.equal(accessCategory('group', 'message_box'), 'group_assistant')
  assert.equal(accessCategory(undefined, undefined), 'direct')
})

test('built-in defaults match the requested policy', () => {
  assert.deepEqual(BUILT_IN_AGENT_ACCESS.direct, { visible: true, push: true, commands: false, reply: true })
  assert.deepEqual(BUILT_IN_AGENT_ACCESS.group, { visible: true, push: true, commands: false, reply: true })
  assert.deepEqual(BUILT_IN_AGENT_ACCESS.group_assistant, { visible: true, push: false, commands: false, reply: false })
})

test('conversation overrides beat connector defaults, which beat built-ins', () => {
  const access = resolveAgentAccess({
    conversationType: 'group', placement: 'normal',
    connectorSettings: { group: { reply: false, push: false } },
    conversationSettings: JSON.stringify({ push: true }),
  })
  assert.deepEqual(
    { visible: access.visible, push: access.push, commands: access.commands, reply: access.reply },
    { visible: true, push: true, commands: false, reply: false },
  )
  assert.deepEqual(access.sources, { visible: 'default', push: 'conversation', commands: 'default', reply: 'connector' })
})

test('an invisible conversation is closed to every agent action', () => {
  const access = resolveAgentAccess({
    conversationType: 'direct', conversationSettings: { visible: false, commands: true, reply: true },
  })
  assert.equal(access.push, false)
  assert.equal(access.commands, false)
  assert.equal(access.reply, false)
  assert.equal(access.configured.reply, true, 'the stored choice is kept for when visibility returns')
  assert.equal(commandAuthority({ ...access, commandSenders: ['*'] }, 'a', '').reason, 'not_visible')
})

test('command authority needs commands, a listed sender and any legacy prefix', () => {
  const base = resolveAgentAccess({ conversationType: 'direct' })
  assert.deepEqual(commandAuthority(base, 'alice', 'hi'), { authorized: false, reason: 'commands_disabled' })
  const listed = resolveAgentAccess({ conversationType: 'direct', conversationSettings: { commands: true, commandSenders: ['alice'] } })
  assert.equal(commandAuthority(listed, 'alice', 'hi').authorized, true)
  assert.equal(commandAuthority(listed, 'bob', 'hi').reason, 'sender_not_authorized')
  assert.equal(commandAuthority(listed, '', 'hi').reason, 'sender_not_authorized')
  const nobody = resolveAgentAccess({ conversationType: 'direct', conversationSettings: { commands: true } })
  assert.equal(commandAuthority(nobody, 'alice', 'hi').reason, 'sender_not_authorized', 'an empty list grants nobody')
  const legacy = resolveAgentAccess({
    conversationType: 'direct',
    legacy: legacyEnrollment('trusted', { enabled: true, requiredPrefix: '/agent', allowedSenderIds: [], replyPolicy: 'none' }),
  })
  assert.deepEqual(legacy.commandSenders, ['*'])
  assert.equal(legacy.reply, false)
  assert.equal(commandAuthority(legacy, 'anyone', '/agent run').authorized, true)
  assert.equal(commandAuthority(legacy, 'anyone', 'run').reason, 'command_prefix_missing')
  assert.equal(legacyEnrollment('untrusted', { enabled: true }), null)
  assert.equal(legacyEnrollment('trusted', { enabled: false }), null)
})

test('settings normalization keeps only boolean switches and clean sender lists', () => {
  assert.deepEqual(normalizeConnectorAgentSettings({ direct: { push: false, reply: 'no' }, other: { push: true }, group: {} }),
    { direct: { push: false } })
  assert.deepEqual(normalizeConnectorAgentSettings('not json'), {})
  assert.deepEqual(normalizeConversationAgentSettings({ visible: true, commandSenders: [' a ', 'a', '', 'b', 7] }),
    { visible: true, commandSenders: ['a', 'b', '7'] })
  assert.deepEqual(normalizeConversationAgentSettings({ commandSenders: 'a' }), {})
  assert.equal(normalizeConversationAgentSettings({ commandSenders: Array.from({ length: 300 }, (_, i) => `s${i}`) })
    .commandSenders.length, 200)
})

test('marks encode who sent and who read a message', () => {
  assert.equal(authorRole('inbound', null), 'contact')
  assert.equal(authorRole('outbound', 'agent:worker'), 'agent')
  assert.equal(authorRole('outbound', 'subject-1'), 'owner')
  assert.equal(messageMarks({ role: 'contact', commandAuthorized: false }), MESSAGE_MARKS.noCommandAuthority)
  assert.equal(messageMarks({ role: 'contact', commandAuthorized: true, agentQueueState: 'pending' }), 0)
  assert.equal(messageMarks({ role: 'contact', commandAuthorized: true, agentQueueState: 'completed' }), 8)
  assert.equal(messageMarks({ role: 'contact', commandAuthorized: true, ownerReadAt: 't', agentReadAt: 't' }), 12)
  assert.equal(messageMarks({ role: 'agent' }), 1 | 8)
  assert.equal(messageMarks({ role: 'agent', ownerReadAt: 't' }), 1 | 4 | 8)
  assert.equal(messageMarks({ role: 'owner' }), 2 | 4)
  assert.deepEqual(markNames(1 | 4 | 8), ['sent_by_agent', 'read_by_owner', 'read_by_agent'])
  assert.deepEqual(markNames(0), [])
})
