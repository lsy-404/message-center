import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { DatabaseSync } from 'node:sqlite'
import worker from '../cloudflare-worker/worker/index.js'
import { createAdminTestAuth } from './helpers/oidc-fixture.mjs'

const database = new DatabaseSync(':memory:')
database.exec(readFileSync(new URL('../cloudflare-worker/worker/schema.sql', import.meta.url), 'utf8'))
const stamp = '2026-10-15T12:00:00.000Z'
const connectorId = 'instance-access'
const connectorToken = 'c'.repeat(40)
const agentToken = 'g'.repeat(40)
database.prepare(`
  INSERT INTO connector_instances (
    id, kind, channel_label, account_label, display_name, mode, state, capabilities_json, last_seen_at,
    created_at, updated_at
  ) VALUES (?, 'im', 'QQ', 'main', 'QQ', 'cloud_relay', 'online', '["receive_text","send_text"]', ?, ?, ?)
`).run(connectorId, stamp, stamp, stamp)

function statement(sql) {
  let args = []
  return {
    bind(...values) { args = values; return this },
    async first() { return database.prepare(sql).get(...args) ?? null },
    async all() { return { results: database.prepare(sql).all(...args) } },
    async run() {
      const result = database.prepare(sql).run(...args)
      return { meta: { changes: Number(result.changes) } }
    },
  }
}
const auth = await createAdminTestAuth({
  DB: {
    prepare: statement,
    async batch(statements) { return Promise.all(statements.map((item) => item.run())) },
  },
  CONNECTOR_TOKENS: JSON.stringify({ [connectorId]: connectorToken }),
  AGENT_TOKEN: agentToken,
})
const { env } = auth

let sequence = 0
async function postEvent(conversationExternalId, fields = {}) {
  sequence += 1
  const externalId = `event-${sequence}`
  const response = await worker.fetch(new Request('https://message.example.com/api/connectors/events', {
    method: 'POST',
    headers: { authorization: `Bearer ${connectorToken}`, 'x-connector-id': connectorId, 'content-type': 'application/json' },
    body: JSON.stringify({ connectorId, messages: [{
      externalId, conversationExternalId, conversationTitle: conversationExternalId,
      senderId: 'alice', senderName: 'Alice', body: `message ${sequence}`,
      occurredAt: new Date(Date.parse(stamp) + sequence * 1000).toISOString(),
      conversationType: 'direct', trigger: 'direct', attachments: [], ...fields,
    }] }),
  }), env, {})
  assert.equal(response.status, 200, await response.clone().text())
  return database.prepare('SELECT id, conversation_id FROM messages WHERE external_id = ?').get(externalId)
}

function queued(messageId) {
  return database.prepare('SELECT COUNT(*) AS total FROM agent_queue WHERE message_id = ?').get(messageId).total === 1
}

async function admin(path, options = {}) {
  const response = await worker.fetch(new Request(`https://message.example.com${path}`, {
    ...options,
    headers: { ...auth.headers, ...(options.body ? { 'content-type': 'application/json' } : {}) },
  }), env, {})
  return { status: response.status, body: await response.json() }
}

async function agent(name, args) {
  const response = await worker.fetch(new Request('https://message.example.com/mcp', {
    method: 'POST',
    headers: { authorization: `Bearer ${agentToken}`, 'content-type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: args } }),
  }), env, {})
  const payload = await response.json()
  return payload.result.isError ? { error: payload.result.content[0].text } : payload.result.structuredContent
}

const consumerId = 'consumer-access'

// Built-in defaults: direct chats and group mentions are pushed; groups kept
// in the group assistant are visible but never pushed.
const direct = await postEvent('dm-alice')
const groupMention = await postEvent('group-work', {
  conversationType: 'group', trigger: 'mention', placement: 'normal', senderId: 'bob', senderName: 'Bob',
})
const assistantMention = await postEvent('group-folded', {
  conversationType: 'group', trigger: 'mention', placement: 'folded', senderId: 'bob', senderName: 'Bob',
})
assert.equal(queued(direct.id), true, 'direct messages are pushed by default')
assert.equal(queued(groupMention.id), true, 'group mentions are pushed by default')
assert.equal(queued(assistantMention.id), false, 'group-assistant mentions are not pushed by default')

const listed = await agent('listen_messages', { consumerId })
assert.deepEqual(listed.candidates.map((item) => item.messageId).sort(), [direct.id, groupMention.id].sort())

const directClaim = await agent('claim_message', { consumerId, messageId: direct.id })
assert.equal(directClaim.acquired, true)
const directScope = directClaim.message.scope
assert.deepEqual(directScope.access, { category: 'direct', visible: true, push: true, commands: false, reply: true })
assert.equal(directScope.commandAuthority, false)
assert.equal(directScope.reason, 'commands_disabled')
assert.equal(directScope.trustTier, 'untrusted')
assert.equal(directScope.replyPolicy, 'informational')
assert.equal(directClaim.message.sender.commandAuthority, false)
assert.equal(directClaim.message.marks, 8 | 16, 'claimed contact message: read by agent, sender without command authority')
assert.deepEqual(directClaim.message.markNames, ['read_by_agent', 'no_command_authority'])
assert.ok(database.prepare('SELECT agent_read_at FROM messages WHERE id = ?').get(direct.id).agent_read_at)

const directReply = await agent('reply_message', {
  consumerId, messageId: direct.id, leaseToken: directClaim.message.leaseToken,
  clientRequestId: 'reply-direct-0001', text: 'AI reply',
})
assert.equal(directReply.error, undefined, 'direct chats accept replies by default')

const assistantClaim = await agent('claim_message', { consumerId, messageId: assistantMention.id })
assert.equal(assistantClaim.acquired, false)

// Connector-level defaults override the built-in ones per category.
const connectorSettings = await admin(`/api/connectors/${connectorId}/agent-settings`, {
  method: 'PUT', body: JSON.stringify({ settings: { group: { reply: false, visible: 'yes' }, unknown: { push: false } } }),
})
assert.equal(connectorSettings.status, 200)
assert.deepEqual(connectorSettings.body.settings, { group: { reply: false } }, 'only boolean switches of known categories persist')
assert.deepEqual(connectorSettings.body.effective.group, { visible: true, push: true, commands: false, reply: false })
assert.deepEqual(connectorSettings.body.effective.direct, { visible: true, push: true, commands: false, reply: true })

const groupClaim = await agent('claim_message', { consumerId, messageId: groupMention.id })
assert.equal(groupClaim.acquired, true)
assert.equal(groupClaim.message.scope.access.reply, false)
assert.equal(groupClaim.message.scope.replyPolicy, 'none')
const groupReply = await agent('reply_message', {
  consumerId, messageId: groupMention.id, leaseToken: groupClaim.message.leaseToken,
  clientRequestId: 'reply-group-0001', text: 'must be rejected',
})
assert.equal(groupReply.error, 'reply_not_allowed_by_policy')

// Conversation overrides beat connector defaults.
const assistantSettings = await admin(`/api/conversations/${assistantMention.conversation_id}/agent-settings`, {
  method: 'PUT', body: JSON.stringify({ settings: { push: true, reply: true } }),
})
assert.equal(assistantSettings.status, 200)
assert.equal(assistantSettings.body.category, 'group_assistant')
assert.deepEqual(assistantSettings.body.inherited, { visible: true, push: false, commands: false, reply: false })
assert.deepEqual(assistantSettings.body.effective, { category: 'group_assistant', visible: true, push: true, commands: false, reply: true })
assert.deepEqual(assistantSettings.body.sources, { visible: 'default', push: 'conversation', commands: 'default', reply: 'conversation' })
const assistantMentionAgain = await postEvent('group-folded', {
  conversationType: 'group', trigger: 'mention', placement: 'folded', senderId: 'bob', senderName: 'Bob',
})
assert.equal(queued(assistantMentionAgain.id), true, 'a conversation override can enable push')

// Command authority requires the conversation to accept commands and the
// sender to be listed; everyone else is marked without authority.
await admin(`/api/conversations/${direct.conversation_id}/agent-settings`, {
  method: 'PUT', body: JSON.stringify({ settings: { commands: true, commandSenders: ['alice', 'alice', ''] } }),
})
const commandMessage = await postEvent('dm-alice', { body: 'please summarize' })
const commandClaim = await agent('claim_message', { consumerId, messageId: commandMessage.id })
assert.equal(commandClaim.message.scope.commandAuthority, true)
assert.equal(commandClaim.message.scope.trustTier, 'trusted')
assert.equal(commandClaim.message.scope.replyPolicy, 'scoped_agent')
assert.equal(commandClaim.message.marks, 8, 'authorized sender carries no "no command authority" mark')

await admin(`/api/conversations/${groupMention.conversation_id}/agent-settings`, {
  method: 'PUT', body: JSON.stringify({ settings: { commands: true, commandSenders: ['carol'] } }),
})
const groupCommand = await postEvent('group-work', {
  conversationType: 'group', trigger: 'mention', placement: 'normal', senderId: 'bob', senderName: 'Bob',
})
const groupCommandClaim = await agent('claim_message', { consumerId, messageId: groupCommand.id })
assert.equal(groupCommandClaim.message.scope.commandAuthority, false)
assert.equal(groupCommandClaim.message.scope.reason, 'sender_not_authorized')
assert.equal(groupCommandClaim.message.marks & 16, 16)
const groupSettings = await admin(`/api/conversations/${groupMention.conversation_id}/agent-settings`)
assert.deepEqual(groupSettings.body.senders.map((sender) => [sender.id, sender.name, sender.commandAuthority]), [['bob', 'Bob', false]])
assert.deepEqual(groupSettings.body.commandSenders, ['carol'])

// Hiding a conversation removes it from the queue and from pull reads.
const hidden = await postEvent('dm-hidden')
assert.equal(queued(hidden.id), true)
await admin(`/api/conversations/${hidden.conversation_id}/agent-settings`, {
  method: 'PUT', body: JSON.stringify({ settings: { visible: false } }),
})
const afterHide = await agent('listen_messages', { consumerId })
assert.equal(afterHide.candidates.some((item) => item.messageId === hidden.id), false)
assert.equal(queued(hidden.id), false, 'pending items of a hidden conversation are dropped')
assert.equal((await agent('read_messages', { consumerId, conversationId: hidden.conversation_id })).error,
  'conversation_not_visible_to_agent')
const hiddenLater = await postEvent('dm-hidden')
assert.equal(queued(hiddenLater.id), false)
const visibleConversations = await agent('list_conversations', {})
assert.equal(visibleConversations.conversations.some((item) => item.id === hidden.conversation_id), false)
const folded = visibleConversations.conversations.find((item) => item.id === assistantMention.conversation_id)
assert.equal(folded.conversationType, 'group')
assert.equal(folded.access.category, 'group_assistant')

// Pull reads mark messages read by the agent without a reply lease.
const readFolded = await agent('read_messages', { consumerId, conversationId: assistantMention.conversation_id, limit: 1 })
assert.deepEqual(readFolded.messages.map((message) => message.id), [assistantMentionAgain.id])
assert.equal(readFolded.messages[0].marks & 8, 8)
assert.equal(readFolded.nextBefore, readFolded.messages[0].occurredAt)
const olderFolded = await agent('read_messages', {
  consumerId, conversationId: assistantMention.conversation_id, before: readFolded.nextBefore,
})
assert.deepEqual(olderFolded.messages.map((message) => message.id), [assistantMention.id])
assert.equal(olderFolded.nextBefore, null)

// Owner reads are recorded by the inbox and show up as mark 4.
const markRead = await admin(`/api/conversations/${direct.conversation_id}/read`, {
  method: 'POST', body: JSON.stringify({}),
})
assert.equal(markRead.status, 200)
assert.ok(markRead.body.marked >= 2)
const inbox = await admin(`/api/inbox?conversationId=${direct.conversation_id}`)
const byId = new Map(inbox.body.messages.map((message) => [message.id, message]))
assert.equal(byId.get(direct.id).marks, 4 | 8, 'authority follows the current settings: alice now holds it')
assert.equal(byId.get(commandMessage.id).marks, 4 | 8)
assert.equal(byId.get(commandMessage.id).commandAuthority, true)
const agentReply = inbox.body.messages.find((message) => message.authorRole === 'agent')
assert.equal(agentReply.marks, 1 | 4 | 8, 'agent reply: sent and read by agent, read by owner')
for (const message of inbox.body.messages) {
  assert.equal('createdBy' in message || 'agentState' in message, false, 'creator identity and queue internals stay server-side')
}
const inboxConversations = new Map(inbox.body.conversations.map((conversation) => [conversation.id, conversation]))
assert.deepEqual(inboxConversations.get(hidden.conversation_id).agentAccess,
  { category: 'direct', visible: false, push: false, commands: false, reply: false })
assert.equal(inboxConversations.get(groupMention.conversation_id).agentAccess.reply, false)
const inboxConnector = inbox.body.connectors.find((connector) => connector.id === connectorId)
assert.deepEqual(inboxConnector.agentSettings, { group: { reply: false } })
assert.equal(inboxConnector.agentDefaults.group_assistant.push, false)

// Conversations enrolled through the older trust policy keep command authority.
const legacy = await postEvent('dm-legacy', { senderId: 'dave', body: 'legacy instruction' })
database.prepare(`UPDATE conversations SET trust_tier = 'trusted', agent_policy_json = ? WHERE id = ?`).run(
  JSON.stringify({ enabled: true, requiredPrefix: '', allowedSenderIds: [], allowedActions: ['send_text'], replyPolicy: 'ack' }),
  legacy.conversation_id,
)
const legacyClaim = await agent('claim_message', { consumerId, messageId: legacy.id })
assert.equal(legacyClaim.message.scope.commandAuthority, true)
assert.equal(legacyClaim.message.scope.replyPolicy, 'ack')
assert.deepEqual(legacyClaim.message.scope.allowedActions, ['send_text'])

// Settings endpoints are administrator-only.
const anonymous = await worker.fetch(new Request(
  `https://message.example.com/api/conversations/${direct.conversation_id}/agent-settings`,
), env, {})
assert.equal(anonymous.status, 401)
const anonymousRead = await worker.fetch(new Request(
  `https://message.example.com/api/conversations/${direct.conversation_id}/read`, { method: 'POST', body: '{}' },
), env, {})
assert.equal(anonymousRead.status, 401)

console.log('Agent access rules and message marks passed.')
