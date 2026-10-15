import assert from 'node:assert/strict'
import test from 'node:test'
import {
  agentAccessSummary,
  agentCategoryLabel,
  agentKeyCopy,
  describeMarks,
  messageMarkTags,
  setConnectorOverride,
} from '../cloudflare-worker/ui/src/agent-rules.mjs'

const labels = (marks, options) => messageMarkTags(marks, options).map((tag) => tag.label)

test('mark tags show sender and both read states without restating authorship', () => {
  assert.deepEqual(labels(0), ['人未读', 'AI 未读'])
  assert.deepEqual(labels(4 | 8), ['人已读', 'AI 已读'])
  assert.deepEqual(labels(1 | 8), ['AI 发', '人未读'], 'the agent has read what it sent')
  assert.deepEqual(labels(1 | 4 | 8), ['AI 发', '人已读'])
  assert.deepEqual(labels(2 | 4), ['人发', 'AI 未读'], 'the owner has read what the owner sent')
  assert.deepEqual(labels(2 | 4 | 8), ['人发', 'AI 已读'])
})

test('missing command authority is flagged only where commands are accepted', () => {
  assert.deepEqual(labels(4 | 8 | 16), ['人已读', 'AI 已读'])
  assert.deepEqual(labels(4 | 8 | 16, { commandsAccepted: true }), ['人已读', 'AI 已读', '无指令权限'])
  assert.equal(messageMarkTags(16, { commandsAccepted: true }).at(-1).tone, 'warning')
})

test('AI unread is emphasized only for contact messages the agent should process', () => {
  const tone = (marks, options) => messageMarkTags(marks, options).find((tag) => tag.key === 'agent-unread').tone
  assert.equal(tone(4, { agentPushes: true }), 'unread')
  assert.equal(tone(4, { agentPushes: false }), 'muted')
  assert.equal(tone(2 | 4, { agentPushes: true }), 'muted')
})

test('marks describe themselves for tooltips and agents reading the page', () => {
  assert.equal(describeMarks(13), '内部标记 13：AI 发送(1) + 人已读(4) + AI 已读(8)')
  assert.equal(describeMarks(0), '内部标记 0')
  assert.equal(describeMarks(undefined), '内部标记 0')
})

test('rule summaries and labels follow the conversation category', () => {
  assert.deepEqual(agentAccessSummary({ category: 'direct', visible: true, push: true, commands: false, reply: true }),
    ['主动处理', '可回复', '无指令'])
  assert.deepEqual(agentAccessSummary({ category: 'group', visible: true, push: true, commands: true, reply: false }),
    ['@时处理', '不回复', '接受指令'])
  assert.deepEqual(agentAccessSummary({ category: 'group_assistant', visible: true, push: false, commands: false, reply: false }),
    ['不推送', '不回复', '无指令'])
  assert.deepEqual(agentAccessSummary({ category: 'direct', visible: false, push: false, commands: false, reply: false }),
    ['AI 不可见'])
  assert.deepEqual(agentAccessSummary(null), [])
  assert.equal(agentCategoryLabel('group_assistant'), '群助手中的群聊')
  assert.equal(agentKeyCopy('push', 'direct').label, '主动推送处理')
  assert.equal(agentKeyCopy('push', 'group').label, '@或关键词时推送')
})

test('connector overrides change one switch and keep the rest', () => {
  const original = { direct: { reply: false }, group: {} }
  const next = setConnectorOverride(original, 'group', 'push', false)
  assert.deepEqual(next, { direct: { reply: false }, group: { push: false } })
  assert.deepEqual(original, { direct: { reply: false }, group: {} }, 'input is not mutated')
  assert.deepEqual(setConnectorOverride(undefined, 'direct', 'visible', true), { direct: { visible: true } })
})
