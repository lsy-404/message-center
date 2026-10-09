const STORAGE_PREFIX = 'message-center.pending-send.v1:'
const FINGERPRINT_RE = /^[a-f0-9]{64}$/
const REQUEST_ID_RE = /^web-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i

export async function getPendingSendRequestKey(conversationId, body, attachmentIds,
  storage = globalThis.localStorage, cryptoProvider = globalThis.crypto) {
  if (typeof conversationId !== 'string' || !conversationId
      || typeof body !== 'string'
      || !Array.isArray(attachmentIds)
      || attachmentIds.some((id) => typeof id !== 'string' || !id)) {
    throw new Error('invalid_send_request_fingerprint')
  }
  if (!storage || typeof storage.getItem !== 'function' || typeof storage.setItem !== 'function') {
    throw new Error('send_request_storage_unavailable')
  }
  if (!cryptoProvider?.subtle?.digest || typeof cryptoProvider.randomUUID !== 'function') {
    throw new Error('send_request_crypto_unavailable')
  }

  const source = JSON.stringify([conversationId, body, attachmentIds])
  const digest = await cryptoProvider.subtle.digest('SHA-256', new TextEncoder().encode(source))
  const fingerprint = [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, '0')).join('')
  const storageKey = `${STORAGE_PREFIX}${fingerprint}`
  const existing = storage.getItem(storageKey)
  if (existing !== null) {
    if (!REQUEST_ID_RE.test(existing)) throw new Error('pending_send_request_corrupt')
    return { fingerprint, clientRequestId: existing }
  }

  const clientRequestId = `web-${cryptoProvider.randomUUID()}`
  storage.setItem(storageKey, clientRequestId)
  const persisted = storage.getItem(storageKey)
  if (!REQUEST_ID_RE.test(persisted || '')) throw new Error('send_request_persistence_failed')
  return { fingerprint, clientRequestId: persisted }
}

export function clearPendingSendRequestKey(fingerprint, clientRequestId,
  storage = globalThis.localStorage) {
  if (!FINGERPRINT_RE.test(fingerprint) || !REQUEST_ID_RE.test(clientRequestId)
      || !storage || typeof storage.getItem !== 'function'
      || typeof storage.removeItem !== 'function') {
    throw new Error('invalid_send_request_cleanup')
  }
  const storageKey = `${STORAGE_PREFIX}${fingerprint}`
  if (storage.getItem(storageKey) !== clientRequestId) return false
  storage.removeItem(storageKey)
  return true
}

export function isAcceptedSendResponse(value) {
  return Boolean(value && typeof value === 'object'
    && value.ok === true
    && typeof value.messageId === 'string' && value.messageId.length > 0
    && typeof value.commandId === 'string' && value.commandId.length > 0)
}
