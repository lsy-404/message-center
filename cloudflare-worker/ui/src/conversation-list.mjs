export const CONVERSATION_PAGE_SIZE = 100

export function filterConversations(conversations, options = {}) {
  const connectorId = String(options.connectorId || '')
  const channelLabel = String(options.channelLabel || '')
  const query = String(options.query || '').trim().toLowerCase()
  const getChannelLabel = options.getChannelLabel

  return conversations.filter((conversation) => {
    if (connectorId && conversation.connectorId !== connectorId) return false
    if (channelLabel) {
      const label = getChannelLabel
        ? getChannelLabel(conversation)
        : String(conversation.connectorChannelLabel || conversation.connectorKind || '')
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
