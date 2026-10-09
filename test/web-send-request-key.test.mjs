import assert from 'node:assert/strict'
import test from 'node:test'
import { webcrypto } from 'node:crypto'
import {
  clearPendingSendRequestKey,
  getPendingSendRequestKey,
  isAcceptedSendResponse,
} from '../cloudflare-worker/ui/src/send-request-key.mjs'

class MemoryStorage {
  values = new Map()

  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null
  }

  setItem(key, value) {
    this.values.set(key, String(value))
  }

  removeItem(key) {
    this.values.delete(key)
  }
}

function cryptoWithIds(...ids) {
  return { subtle: webcrypto.subtle, randomUUID: () => ids.shift() }
}

const firstId = '123e4567-e89b-12d3-a456-426614174001'
const secondId = '123e4567-e89b-12d3-a456-426614174002'

test('reuses the durable request key after reload without persisting message text', async () => {
  const storage = new MemoryStorage()
  const first = await getPendingSendRequestKey(
    'conversation-one', 'private message text', ['file-one'], storage, cryptoWithIds(firstId),
  )
  const afterReload = await getPendingSendRequestKey(
    'conversation-one', 'private message text', ['file-one'], storage, cryptoWithIds(secondId),
  )

  assert.deepEqual(afterReload, first)
  const persisted = [...storage.values.entries()]
  assert.equal(persisted.length, 1)
  assert.match(persisted[0][0], /^message-center\.pending-send\.v1:[a-f0-9]{64}$/)
  assert.equal(persisted[0][1], `web-${firstId}`)
  assert.doesNotMatch(JSON.stringify(persisted), /private message text|conversation-one|file-one/)
})

test('keeps different payloads distinct and reuses a prior key if the draft is restored', async () => {
  const storage = new MemoryStorage()
  const crypto = cryptoWithIds(firstId, secondId)
  const original = await getPendingSendRequestKey('conversation-one', 'first text', [], storage, crypto)
  const edited = await getPendingSendRequestKey('conversation-one', 'second text', [], storage, crypto)
  const restored = await getPendingSendRequestKey('conversation-one', 'first text', [], storage, crypto)
  const otherConversation = await getPendingSendRequestKey(
    'conversation-two', 'first text', [], storage, cryptoWithIds('123e4567-e89b-12d3-a456-426614174003'),
  )

  assert.notEqual(original.fingerprint, edited.fingerprint)
  assert.notEqual(original.fingerprint, otherConversation.fingerprint)
  assert.equal(restored.clientRequestId, original.clientRequestId)
  assert.equal(storage.values.size, 3)
})

test('clears only the matching request key after durable command acceptance', async () => {
  const storage = new MemoryStorage()
  const pending = await getPendingSendRequestKey(
    'conversation-one', 'message', [], storage, cryptoWithIds(firstId),
  )

  assert.equal(isAcceptedSendResponse({ ok: true, messageId: 'message-id', commandId: 'command-id' }), true)
  assert.equal(isAcceptedSendResponse({ ok: true, messageId: 'message-id' }), false)
  assert.equal(isAcceptedSendResponse({ ok: false, messageId: 'message-id', commandId: 'command-id' }), false)
  assert.equal(clearPendingSendRequestKey(pending.fingerprint, `web-${secondId}`, storage), false)
  assert.equal(storage.values.size, 1)
  assert.equal(clearPendingSendRequestKey(pending.fingerprint, pending.clientRequestId, storage), true)
  assert.equal(storage.values.size, 0)
})

test('fails closed when persistence or stored request data is unavailable', async () => {
  const storage = new MemoryStorage()
  storage.setItem = () => { throw new Error('storage denied') }
  await assert.rejects(
    getPendingSendRequestKey('conversation-one', 'message', [], storage, cryptoWithIds(firstId)),
    /storage denied/,
  )
  storage.setItem = MemoryStorage.prototype.setItem
  const pending = await getPendingSendRequestKey(
    'conversation-one', 'message', [], storage, cryptoWithIds(secondId),
  )
  storage.values.set('message-center.pending-send.v1:' + pending.fingerprint, 'invalid-request-id')
  await assert.rejects(
    getPendingSendRequestKey('conversation-one', 'message', [], storage, cryptoWithIds(firstId)),
    /pending_send_request_corrupt/,
  )
})
