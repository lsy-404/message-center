export type ConversationListFilter = {
  connectorKind?: string
  connectorId?: string
  channelLabel?: string
  query?: string
  unreadOnly?: boolean
  getChannelLabel?: (conversation: any) => string
}

export const CONVERSATION_PAGE_SIZE: number
export function normalizeChannelLabel(value: unknown): string
export function isQQGroupAssistantConversation<T extends Record<string, any>>(conversation: T): boolean
export function filterQQGroupAssistantConversations<T extends Record<string, any>>(conversations: T[]): T[]
export function filterConversations<T extends Record<string, any>>(
  conversations: T[], options?: ConversationListFilter,
): T[]
export function pageConversations<T>(conversations: T[], pageIndex?: number, pageSize?: number): T[]
export function conversationPageCount(totalCount: number, pageSize?: number): number
export function nextConversationPage(currentPage: number, totalCount: number, pageSize?: number): number
export function previousConversationPage(currentPage: number): number
