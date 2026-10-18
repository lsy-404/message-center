import assert from 'node:assert/strict'
import test from 'node:test'
import {
  MAX_CONVERSATION_LIST_LEVELS,
  QQ_GROUP_ASSISTANT_FOLDER_ID,
  buildConversationListModel,
  canEnterConversationListFolder,
  enterConversationListFolder,
  filterConversations,
  filterQQGroupAssistantConversations,
  resolveConversationSelection,
} from '../cloudflare-worker/ui/src/conversation-list.mjs'

const conversations = [
  { id: 'folded', connectorKind: 'qq', connectorChannelLabel: 'QQ', conversationType: 'group', placement: 'folded', unreadCount: 2, title: 'Folded group' },
  { id: 'message-box', connectorKind: 'qq', connectorChannelLabel: 'QQ', conversationType: 'group', placement: 'message_box', unreadCount: 0, title: 'Box group' },
  { id: 'normal-group', connectorKind: 'qq', connectorChannelLabel: 'QQ', conversationType: 'group', placement: 'normal', unreadCount: 3, title: 'Normal group' },
  { id: 'direct', connectorKind: 'qq', connectorChannelLabel: 'QQ', conversationType: 'direct', placement: 'folded', unreadCount: 1, title: 'Direct chat' },
  { id: 'other-channel', connectorKind: 'wechat', connectorChannelLabel: '微信', conversationType: 'group', placement: 'folded', unreadCount: 4, title: 'Other group' },
  { id: 'unknown-placement', connectorKind: 'qq', connectorChannelLabel: 'QQ', conversationType: 'group', placement: 'unknown', unreadCount: 0, title: 'Unknown placement' },
]

const qqConversations = filterConversations(conversations, { connectorKind: 'qq' })

test('QQ group assistant membership requires QQ, group type, and observed folded or message-box placement', () => {
  assert.deepEqual(filterQQGroupAssistantConversations(conversations).map(({ id }) => id), ['folded', 'message-box'])
})

test('QQ root shows one group-assistant folder row and keeps non-assistant conversations at level one', () => {
  const model = buildConversationListModel(qqConversations, {
    qqRoot: true,
    selectedId: 'folded',
    rootTitle: 'QQ',
  })

  assert.equal(model.level, 1)
  assert.equal(model.title, 'QQ')
  assert.deepEqual(model.conversations.map(({ id }) => id), ['normal-group', 'direct', 'unknown-placement'])
  assert.deepEqual(model.folder, {
    kind: 'folder', id: QQ_GROUP_ASSISTANT_FOLDER_ID, title: '群助手', count: 2, unreadCount: 2, active: true,
  })
  assert.ok(model.selectionConversations.some(({ id }) => id === 'folded'))
})

test('opening 群助手 is a flat second-level group list across the observed placements', () => {
  const path = enterConversationListFolder([], QQ_GROUP_ASSISTANT_FOLDER_ID)
  const model = buildConversationListModel(qqConversations, { path, qqRoot: true })

  assert.deepEqual(path, [QQ_GROUP_ASSISTANT_FOLDER_ID])
  assert.equal(model.level, 2)
  assert.deepEqual(model.conversations.map(({ id }) => id), ['folded', 'message-box'])
  assert.deepEqual(new Set(model.conversations.map(({ placement }) => placement)), new Set(['folded', 'message_box']))
  assert.equal(model.folder, null, 'placement is not a fabricated child-folder hierarchy')
})

test('search and unread filters determine folder presence and counts within the QQ root scope', () => {
  const searched = buildConversationListModel(filterConversations(qqConversations, { query: 'box group' }), {
    qqRoot: true,
  })
  assert.deepEqual(searched.folder && [searched.folder.count, searched.folder.unreadCount], [1, 0])

  const unread = buildConversationListModel(filterConversations(qqConversations, { unreadOnly: true }), {
    qqRoot: true,
  })
  assert.deepEqual(unread.folder && [unread.folder.count, unread.folder.unreadCount], [1, 2])
  assert.deepEqual(unread.conversations.map(({ id }) => id), ['normal-group', 'direct'])

  const noMatchingAssistant = buildConversationListModel(
    filterConversations(qqConversations, { query: 'no matching group' }), { qqRoot: true },
  )
  assert.equal(noMatchingAssistant.folder, null)
})

test('selection remains attached to a nested group at the QQ root and is scope-bound inside 群助手', () => {
  const root = buildConversationListModel(qqConversations, { qqRoot: true, selectedId: 'folded' })
  assert.equal(resolveConversationSelection(root.selectionConversations, 'folded').action, 'keep')

  const groupPath = [QQ_GROUP_ASSISTANT_FOLDER_ID]
  const assistant = buildConversationListModel(qqConversations, { path: groupPath, qqRoot: true })
  assert.equal(resolveConversationSelection(assistant.selectionConversations, 'message-box').action, 'keep')
  assert.deepEqual(resolveConversationSelection(assistant.selectionConversations, 'wechat-selection'), {
    action: 'select', conversation: assistant.conversations[0],
  })
  assert.deepEqual(resolveConversationSelection([], 'message-box'), { action: 'clear', conversation: null })
})

test('conversation navigation is bounded to three list levels', () => {
  assert.equal(MAX_CONVERSATION_LIST_LEVELS, 3)
  assert.equal(canEnterConversationListFolder([]), true)
  const secondLevel = enterConversationListFolder([], QQ_GROUP_ASSISTANT_FOLDER_ID)
  assert.equal(canEnterConversationListFolder(secondLevel), true)
  const thirdLevel = enterConversationListFolder(secondLevel, 'observed-folder-id')
  assert.equal(thirdLevel.length + 1, MAX_CONVERSATION_LIST_LEVELS)
  assert.equal(canEnterConversationListFolder(thirdLevel), false)
  assert.deepEqual(enterConversationListFolder(thirdLevel, 'too-deep'), thirdLevel)
})

test('the all-channel inbox remains flat and shows QQ group conversations as conversations', () => {
  const model = buildConversationListModel(conversations, { qqRoot: false })
  assert.equal(model.folder, null)
  assert.deepEqual(model.conversations.map(({ id }) => id), conversations.map(({ id }) => id))
})

test('ordinary search still finds folded QQ groups', () => {
  assert.deepEqual(filterConversations(conversations, { query: 'box group' }).map(({ id }) => id), ['message-box'])
})
