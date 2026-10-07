export function createInboxReadGate(): {
  begin(conversationId: string): { conversationId: string; controller: AbortController }
  isCurrent(request: { conversationId: string; controller: AbortController }, selectedConversationId: string): boolean
  isActive(request: { conversationId: string; controller: AbortController }): boolean
  isBusy(): boolean
  finish(request: { conversationId: string; controller: AbortController }): void
  cancel(): void
}

export function createInboxRefreshLoop(
  refresh: () => Promise<unknown>,
  isEnabled: () => boolean,
  timers?: Pick<Window, 'setTimeout' | 'clearTimeout'>,
): {
  start(immediate?: boolean): void
  stop(): void
  wake(): void
}
