import assert from 'node:assert/strict'
import test from 'node:test'
import {
  filterConversations,
  filterQQGroupAssistantConversations,
  resolveConversationSelection,
} from '../cloudflare-worker/ui/src/conversation-list.mjs'

const conversations = [
  { id: 'folded', connectorKind: 'qq', connectorChannelLabel: 'Custom QQ label', conversationType: 'group', placement: 'folded', unreadCount: 2, title: 'Folded group' },
  { id: 'message-box', connectorKind: 'qq', conversationType: 'group', placement: 'message_box', unreadCount: 0, title: 'Box group' },
  { id: 'normal-group', connectorKind: 'qq', conversationType: 'group', placement: 'normal', unreadCount: 3, title: 'Normal group' },
  { id: 'direct', connectorKind: 'qq', conversationType: 'direct', placement: 'folded', unreadCount: 1, title: 'Direct chat' },
  { id: 'other-channel', connectorKind: 'wechat', conversationType: 'group', placement: 'folded', unreadCount: 4, title: 'Other group' },
  { id: 'unknown-placement', connectorKind: 'qq', conversationType: 'group', placement: 'unknown', unreadCount: 0, title: 'Unknown group' },
]

test('QQ group assistant includes only QQ groups in folded or message-box placement', () => {
  assert.deepEqual(filterQQGroupAssistantConversations(conversations).map(({ id }) => id), ['folded', 'message-box'])
})

test('assistant filtering composes with existing search and unread filters', () => {
  const searched = filterConversations(conversations, { query: 'folded group' })
  assert.deepEqual(filterQQGroupAssistantConversations(searched).map(({ id }) => id), ['folded'])

  const unread = filterConversations(conversations, { unreadOnly: true })
  assert.deepEqual(filterQQGroupAssistantConversations(unread).map(({ id }) => id), ['folded'])
})

test('ordinary conversation search still finds folded QQ groups', () => {
  assert.deepEqual(filterConversations(conversations, { query: 'box group' }).map(({ id }) => id), ['message-box'])
})

test('QQ list filtering uses connector kind even when its display label is customized', () => {
  assert.deepEqual(
    filterConversations(conversations, { connectorKind: 'qq' }).map(({ id }) => id),
    ['folded', 'message-box', 'normal-group', 'direct', 'unknown-placement'],
  )
})

test('view changes keep an in-scope selection, select the first match, or clear an empty scope', () => {
  const candidates = filterQQGroupAssistantConversations(conversations)
  assert.deepEqual(resolveConversationSelection(candidates, 'message-box'), {
    action: 'keep', conversation: null,
  })
  assert.deepEqual(resolveConversationSelection(candidates, 'wechat-selection'), {
    action: 'select', conversation: candidates[0],
  })
  assert.deepEqual(resolveConversationSelection([], 'wechat-selection'), {
    action: 'clear', conversation: null,
  })
})
