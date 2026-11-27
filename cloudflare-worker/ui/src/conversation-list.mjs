export const CONVERSATION_PAGE_SIZE = 100
export const MAX_CONVERSATION_LIST_LEVELS = 3
export const QQ_GROUP_ASSISTANT_FOLDER_ID = 'qq-group-assistant'

export function normalizeChannelLabel(value) {
  const label = String(value || '')
  const knownLabel = label.trim().toLowerCase()
  if (knownLabel === 'qq') return 'QQ'
  if (knownLabel === 'wechat' || knownLabel === '微信') return '微信'
  return label
}

export const WECHAT_FOLDED_CHATS_FOLDER_ID = 'wechat-folded-chats'

function isFoldedPlacement(conversation) {
  return conversation.placement === 'folded' || conversation.placement === 'message_box'
}

const CONVERSATION_FOLDERS = [
  {
    id: QQ_GROUP_ASSISTANT_FOLDER_ID,
    scopeKind: 'qq',
    title: '群助手',
    unit: '个群聊',
    contains: (conversation) => conversation.connectorKind === 'qq'
      && conversation.conversationType === 'group'
      && isFoldedPlacement(conversation),
  },
  {
    id: WECHAT_FOLDED_CHATS_FOLDER_ID,
    scopeKind: 'wechat',
    title: '折叠的聊天',
    unit: '个会话',
    contains: (conversation) => (conversation.connectorKind === 'wechat'
      || normalizeChannelLabel(conversation.connectorChannelLabel) === '微信')
      && isFoldedPlacement(conversation),
  },
]

export function getConversationFolder(folderId) {
  return CONVERSATION_FOLDERS.find((folder) => folder.id === folderId) || null
}

export function conversationFolderOf(conversation) {
  return CONVERSATION_FOLDERS.find((folder) => folder.contains(conversation)) || null
}

export function isQQGroupAssistantConversation(conversation) {
  return getConversationFolder(QQ_GROUP_ASSISTANT_FOLDER_ID).contains(conversation)
}

export function filterQQGroupAssistantConversations(conversations) {
  return conversations.filter(isQQGroupAssistantConversation)
}

export function unreadTotal(conversations) {
  return conversations.reduce(
    (total, conversation) => total + (conversation.muted ? 0 : Math.max(0, Number(conversation.unreadCount) || 0)), 0,
  )
}

export function normalizeConversationListPath(path) {
  if (!Array.isArray(path)) return []
  return path.slice(0, MAX_CONVERSATION_LIST_LEVELS - 1)
    .filter((segment) => typeof segment === 'string' && segment.trim().length > 0 && segment.length <= 128)
}

export function canEnterConversationListFolder(path) {
  return normalizeConversationListPath(path).length + 2 <= MAX_CONVERSATION_LIST_LEVELS
}

export function enterConversationListFolder(path, folderId) {
  const currentPath = normalizeConversationListPath(path)
  const id = typeof folderId === 'string' ? folderId.trim() : ''
  if (!id || id.length > 128 || !canEnterConversationListFolder(currentPath)) return currentPath
  return [...currentPath, id]
}

export function buildConversationListModel(conversations, options = {}) {
  const items = Array.isArray(conversations) ? conversations : []
  const path = normalizeConversationListPath(options.path)
  const openFolder = getConversationFolder(path[0])

  if (openFolder) {
    const folderConversations = items.filter(openFolder.contains)
    return {
      path: [openFolder.id],
      level: 2,
      title: openFolder.title,
      conversations: folderConversations,
      scopeConversations: folderConversations,
      selectionConversations: folderConversations,
      folders: [],
    }
  }

  const scopeKinds = Array.isArray(options.scopeKinds) ? options.scopeKinds : []
  const scopeFolders = CONVERSATION_FOLDERS.filter((folder) => scopeKinds.includes(folder.scopeKind))
  const membersOf = scopeFolders.map((folder) => items.filter(folder.contains))
  const rootConversations = scopeFolders.length
    ? items.filter((conversation) => !scopeFolders.some((folder) => folder.contains(conversation)))
    : items
  const selectedInFolder = options.selectedId
    ? membersOf.flat().find((conversation) => conversation.id === options.selectedId)
    : null
  const selectionConversations = selectedInFolder
    ? [...rootConversations, selectedInFolder]
    : rootConversations

  return {
    path: [],
    level: 1,
    title: options.rootTitle || '',
    conversations: rootConversations,
    scopeConversations: items,
    selectionConversations,
    folders: scopeFolders.flatMap((folder, index) => {
      const members = membersOf[index]
      if (!members.length) return []
      return [{
        kind: 'folder',
        id: folder.id,
        title: folder.title,
        count: members.length,
        unreadCount: unreadTotal(members),
        active: members.includes(selectedInFolder),
      }]
    }),
  }
}

export function resolveConversationSelection(conversations, selectedId) {
  if (conversations.some((conversation) => conversation.id === selectedId)) {
    return { action: 'keep', conversation: null }
  }
  const conversation = conversations[0]
  return conversation
    ? { action: 'select', conversation }
    : { action: 'clear', conversation: null }
}

export function filterConversations(conversations, options = {}) {
  const connectorKind = String(options.connectorKind || '')
  const connectorId = String(options.connectorId || '')
  const channelLabel = normalizeChannelLabel(options.channelLabel || '')
  const query = String(options.query || '').trim().toLowerCase()
  const getChannelLabel = options.getChannelLabel
  const unreadOnly = Boolean(options.unreadOnly)

  return conversations.filter((conversation) => {
    if (connectorKind && conversation.connectorKind !== connectorKind) return false
    if (connectorId && conversation.connectorId !== connectorId) return false
    if (unreadOnly && !(Number(conversation.unreadCount) > 0)) return false
    if (channelLabel) {
      const label = normalizeChannelLabel(getChannelLabel
        ? getChannelLabel(conversation)
        : String(conversation.connectorChannelLabel || conversation.connectorKind || ''))
      if (label !== channelLabel) return false
    }
    if (!query) return true
    const searchable = [
      conversation.title,
      conversation.avatarLabel,
      conversation.lastMessagePreview,
      conversation.connectorChannelLabel,
      conversation.connectorKind,
    ].map((value) => String(value || '')).join(' ').toLowerCase()
    return searchable.includes(query)
  })
}

export function pageConversations(conversations, pageIndex = 0, pageSize = CONVERSATION_PAGE_SIZE) {
  const page = Number.isFinite(pageIndex) ? Math.max(0, Math.floor(pageIndex)) : 0
  const size = Number.isFinite(pageSize) ? Math.max(1, Math.floor(pageSize)) : CONVERSATION_PAGE_SIZE
  const start = page * size
  return conversations.slice(start, start + size)
}

export function conversationPageCount(totalCount, pageSize = CONVERSATION_PAGE_SIZE) {
  const total = Number.isFinite(totalCount) ? Math.max(0, Math.floor(totalCount)) : 0
  const size = Number.isFinite(pageSize) ? Math.max(1, Math.floor(pageSize)) : CONVERSATION_PAGE_SIZE
  return Math.ceil(total / size)
}

export function nextConversationPage(currentPage, totalCount, pageSize = CONVERSATION_PAGE_SIZE) {
  const current = Number.isFinite(currentPage) ? Math.max(0, Math.floor(currentPage)) : 0
  return Math.min(current + 1, Math.max(0, conversationPageCount(totalCount, pageSize) - 1))
}

export function previousConversationPage(currentPage) {
  const current = Number.isFinite(currentPage) ? Math.max(0, Math.floor(currentPage)) : 0
  return Math.max(0, current - 1)
}
