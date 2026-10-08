export type ConversationListFilter = {
  connectorId?: string
  channelLabel?: string
  query?: string
  getChannelLabel?: (conversation: any) => string
}

export const CONVERSATION_PAGE_SIZE: number
export function filterConversations<T extends Record<string, any>>(
  conversations: T[], options?: ConversationListFilter,
): T[]
export function pageConversations<T>(conversations: T[], pageIndex?: number, pageSize?: number): T[]
export function conversationPageCount(totalCount: number, pageSize?: number): number
export function nextConversationPage(currentPage: number, totalCount: number, pageSize?: number): number
export function previousConversationPage(currentPage: number): number
