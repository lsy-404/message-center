export type ConversationListFilter = {
  connectorKind?: string
  connectorId?: string
  channelLabel?: string
  query?: string
  unreadOnly?: boolean
  getChannelLabel?: (conversation: any) => string
}

export const CONVERSATION_PAGE_SIZE: number
export const MAX_CONVERSATION_LIST_LEVELS: number
export const QQ_GROUP_ASSISTANT_FOLDER_ID: string
export function normalizeChannelLabel(value: unknown): string
export function isQQGroupAssistantConversation<T extends Record<string, any>>(conversation: T): boolean
export function filterQQGroupAssistantConversations<T extends Record<string, any>>(conversations: T[]): T[]
export function normalizeConversationListPath(path: unknown): string[]
export function canEnterConversationListFolder(path: unknown): boolean
export function enterConversationListFolder(path: unknown, folderId: unknown): string[]
export function buildConversationListModel<T extends Record<string, any>>(
  conversations: T[], options?: {
    path?: unknown
    qqRoot?: boolean
    selectedId?: string
    rootTitle?: string
  },
): {
  path: string[]
  level: number
  title: string
  conversations: T[]
  scopeConversations: T[]
  selectionConversations: T[]
  folder: null | { kind: 'folder', id: string, title: string, count: number, unreadCount: number, active: boolean }
}
export function resolveConversationSelection<T extends { id: string }>(
  conversations: T[], selectedId: string,
): { action: 'keep' | 'select' | 'clear', conversation: T | null }
export function filterConversations<T extends Record<string, any>>(
  conversations: T[], options?: ConversationListFilter,
): T[]
export function pageConversations<T>(conversations: T[], pageIndex?: number, pageSize?: number): T[]
export function conversationPageCount(totalCount: number, pageSize?: number): number
export function nextConversationPage(currentPage: number, totalCount: number, pageSize?: number): number
export function previousConversationPage(currentPage: number): number
