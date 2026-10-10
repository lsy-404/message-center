import assert from 'node:assert/strict'
import test from 'node:test'
import { filterConversations, normalizeChannelLabel } from '../cloudflare-worker/ui/src/conversation-list.mjs'

const conversations = [
  { id: 'qq-uppercase', connectorId: 'qq-a', externalId: 'qq-native-a', connectorKind: 'im', connectorChannelLabel: 'QQ' },
  { id: 'qq-lowercase', connectorId: 'qq-b', externalId: 'qq-native-b', connectorKind: 'im', connectorChannelLabel: 'qq' },
  { id: 'wechat-label', connectorId: 'wx-a', externalId: 'wx-native-a', connectorKind: 'im', connectorChannelLabel: 'wechat' },
  { id: 'wechat-localized', connectorId: 'wx-b', externalId: 'wx-native-b', connectorKind: 'im', connectorChannelLabel: '微信' },
  { id: 'custom', connectorId: 'custom-a', externalId: 'custom-native', connectorKind: 'im', connectorChannelLabel: 'Study IM' },
]

test('known channel aliases normalize without rewriting custom labels', () => {
  assert.equal(normalizeChannelLabel('QQ'), 'QQ')
  assert.equal(normalizeChannelLabel('qq'), 'QQ')
  assert.equal(normalizeChannelLabel('Qq'), 'QQ')
  assert.equal(normalizeChannelLabel('wechat'), '微信')
  assert.equal(normalizeChannelLabel('WeChat'), '微信')
  assert.equal(normalizeChannelLabel('微信'), '微信')
  assert.equal(normalizeChannelLabel('Study IM'), 'Study IM')
  assert.equal(normalizeChannelLabel(' Study IM '), ' Study IM ')
})

test('normalized filter labels include known aliases and preserve connector isolation', () => {
  assert.deepEqual(
    filterConversations(conversations, { channelLabel: 'qq' }).map(({ id }) => id),
    ['qq-uppercase', 'qq-lowercase'],
  )
  assert.deepEqual(
    filterConversations(conversations, { channelLabel: 'WeChat' }).map(({ id }) => id),
    ['wechat-label', 'wechat-localized'],
  )
  assert.deepEqual(
    filterConversations(conversations, { channelLabel: 'QQ', connectorId: 'qq-b' }).map(({ id }) => id),
    ['qq-lowercase'],
  )
  assert.deepEqual(
    filterConversations(conversations, { channelLabel: 'Study IM' }).map(({ id }) => id),
    ['custom'],
  )
  assert.equal(conversations[1].connectorId, 'qq-b')
  assert.equal(conversations[1].externalId, 'qq-native-b')
  assert.equal(conversations[1].connectorKind, 'im')
})

test('custom channel-label providers are normalized using the same rule', () => {
  const rows = [{ id: 'one' }, { id: 'two' }]
  assert.deepEqual(
    filterConversations(rows, {
      channelLabel: '微信',
      getChannelLabel: ({ id }) => id === 'one' ? 'wechat' : '微信',
    }),
    rows,
  )
})
