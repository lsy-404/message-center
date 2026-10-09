export type PendingSendRequestKey = {
  fingerprint: string
  clientRequestId: string
}

export function getPendingSendRequestKey(
  conversationId: string,
  body: string,
  attachmentIds: string[],
  storage?: Pick<Storage, 'getItem' | 'setItem'>,
  cryptoProvider?: Crypto,
): Promise<PendingSendRequestKey>

export function clearPendingSendRequestKey(
  fingerprint: string,
  clientRequestId: string,
  storage?: Pick<Storage, 'getItem' | 'removeItem'>,
): boolean

export function isAcceptedSendResponse(value: unknown): boolean
