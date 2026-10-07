import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { DatabaseSync } from 'node:sqlite'
import worker from '../cloudflare-worker/worker/index.js'

const database = new DatabaseSync(':memory:')
database.exec(readFileSync(new URL('../cloudflare-worker/worker/schema.sql', import.meta.url), 'utf8'))
const token = 'c'.repeat(40)
const connectorId = 'connector-media-fixture'
const stamp = '2026-10-07T12:00:00.000Z'
database.prepare(`
  INSERT INTO connector_instances (
    id, kind, account_label, display_name, mode, state, capabilities_json, last_seen_at, created_at, updated_at
  ) VALUES (?, 'im', 'fixture', 'Fixture', 'device_relay', 'online', ?, ?, ?, ?)
`).run(connectorId, JSON.stringify(['receive_text', 'receive_images']), stamp, stamp, stamp)

function makeStatement(sql, args = []) {
  return {
    bind(...values) { return makeStatement(sql, values) },
    async first() { return database.prepare(sql).get(...args) ?? null },
    async all() { return { results: database.prepare(sql).all(...args) } },
    async run() {
      const result = database.prepare(sql).run(...args)
      return { meta: { changes: Number(result.changes) } }
    },
  }
}

const files = new Map()
const env = {
  CONNECTOR_TOKENS: JSON.stringify({ [connectorId]: token }),
  DB: {
    prepare(sql) { return makeStatement(sql) },
    async batch(statements) {
      const results = []
      for (const statement of statements) results.push(await statement.run())
      return results
    },
  },
  FILES: {
    async put(key, value, options) {
      const bytes = new Uint8Array(await new Response(value).arrayBuffer())
      const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
        .map((byte) => byte.toString(16).padStart(2, '0')).join('')
      assert.equal(options.sha256, digest, 'R2 checksum must match uploaded bytes')
      files.set(key, { bytes, customMetadata: options.customMetadata })
      return { size: bytes.length }
    },
    async head(key) {
      const value = files.get(key)
      return value ? { size: value.bytes.length, customMetadata: value.customMetadata } : null
    },
    async get(key) {
      const value = files.get(key)
      return value ? { body: new Blob([value.bytes]).stream() } : null
    },
    async delete(key) { files.delete(key) },
  },
}

async function connectorRequest(path, method, body, extraHeaders = {}) {
  const headers = {
    authorization: `Bearer ${token}`,
    'x-connector-id': connectorId,
    ...extraHeaders,
  }
  if (body && !(body instanceof Uint8Array)) headers['content-type'] = 'application/json'
  return worker.fetch(new Request(`https://message.example.com${path}`, {
    method,
    headers,
    body: body instanceof Uint8Array ? body : JSON.stringify(body),
  }), env, {})
}

async function uploadFile(fileId, conversationExternalId, bytes) {
  const sha256 = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
    .map((byte) => byte.toString(16).padStart(2, '0')).join('')
  const response = await connectorRequest(`/api/connectors/files/${fileId}`, 'PUT', bytes, {
    'content-type': 'image/png',
    'content-length': String(bytes.length),
    'x-conversation-id': conversationExternalId,
    'x-file-external-id': fileId,
    'x-file-name': 'photo.png',
    'x-content-sha256': sha256,
  })
  assert.equal(response.status, 201)
  return { externalId: fileId, fileName: 'photo.png', mimeType: 'image/png', sizeBytes: bytes.length, sha256 }
}

async function postEvent(message) {
  return connectorRequest('/api/connectors/events', 'POST', { connectorId, messages: [message] })
}

async function postGroupBackup(message) {
  return connectorRequest('/api/connectors/group-text-backups', 'POST', { connectorId, messages: [message] })
}

const eventBase = {
  conversationExternalId: 'conversation-direct',
  conversationTitle: 'Direct conversation',
  senderName: 'Sender',
  occurredAt: stamp,
  body: 'existing text',
  conversationType: 'direct',
  trigger: 'direct',
}
const firstEvent = await postEvent({ ...eventBase, externalId: 'message-direct' })
assert.equal(firstEvent.status, 200)
const directMessage = database.prepare("SELECT id, metadata_json, content_type FROM messages WHERE external_id = 'message-direct'").get()
const unreadBefore = database.prepare("SELECT unread_count FROM conversations WHERE external_id = 'conversation-direct'").get().unread_count
const queueBefore = database.prepare('SELECT COUNT(*) AS count FROM agent_queue').get().count
const directAttachment = await uploadFile('file-direct', eventBase.conversationExternalId, new Uint8Array([1, 2, 3]))
const backfilledDirect = await postEvent({ ...eventBase, externalId: 'message-direct', attachments: [directAttachment] })
assert.equal(backfilledDirect.status, 200)
const linkedDirect = database.prepare("SELECT id, message_id, state FROM attachments WHERE external_id = 'file-direct'").get()
assert.equal(linkedDirect.message_id, directMessage.id)
assert.equal(linkedDirect.state, 'received')
const updatedDirect = database.prepare("SELECT metadata_json, content_type FROM messages WHERE external_id = 'message-direct'").get()
assert.equal(JSON.parse(updatedDirect.metadata_json).attachments[0].externalId, 'file-direct')
assert.equal(updatedDirect.content_type, 'mixed')
assert.equal(database.prepare('SELECT COUNT(*) AS count FROM agent_queue').get().count, queueBefore)
assert.equal(database.prepare("SELECT unread_count FROM conversations WHERE external_id = 'conversation-direct'").get().unread_count, unreadBefore)
const attemptedMove = await postEvent({ ...eventBase, externalId: 'message-direct-other', attachments: [directAttachment] })
assert.equal(attemptedMove.status, 400)
assert.equal(database.prepare("SELECT message_id FROM attachments WHERE external_id = 'file-direct'").get().message_id, directMessage.id)

const secondDirectAttachment = await uploadFile('file-direct-conflict', eventBase.conversationExternalId, new Uint8Array([4, 5, 6]))
const conflictingDirect = await postEvent({ ...eventBase, externalId: 'message-direct', body: 'different text', attachments: [secondDirectAttachment] })
assert.equal(conflictingDirect.status, 400)
assert.equal(database.prepare("SELECT message_id FROM attachments WHERE external_id = 'file-direct-conflict'").get().message_id, null)
assert.equal(JSON.parse(database.prepare("SELECT metadata_json FROM messages WHERE external_id = 'message-direct'").get().metadata_json).attachments.length, 1)

const groupBase = {
  externalId: 'message-group',
  conversationExternalId: 'conversation-group',
  conversationTitle: 'Group conversation',
  senderName: 'Group sender',
  occurredAt: stamp,
  body: 'group text',
  conversationType: 'group',
  placement: 'normal',
}
const firstGroup = await postGroupBackup(groupBase)
assert.equal(firstGroup.status, 200)
const groupMessage = database.prepare("SELECT id, metadata_json, content_type FROM messages WHERE external_id = 'message-group'").get()
const groupAttachment = await uploadFile('file-group', groupBase.conversationExternalId, new Uint8Array([7, 8, 9]))
const backfilledGroup = await postGroupBackup({ ...groupBase, attachments: [groupAttachment] })
assert.equal(backfilledGroup.status, 200)
const linkedGroup = database.prepare("SELECT message_id, state FROM attachments WHERE external_id = 'file-group'").get()
assert.equal(linkedGroup.message_id, groupMessage.id)
assert.equal(linkedGroup.state, 'received')
const updatedGroup = database.prepare("SELECT metadata_json, content_type FROM messages WHERE external_id = 'message-group'").get()
assert.equal(JSON.parse(updatedGroup.metadata_json).attachments[0].externalId, 'file-group')
assert.equal(updatedGroup.content_type, 'mixed')
const attemptedGroupMove = await postGroupBackup({ ...groupBase, externalId: 'message-group-other', attachments: [groupAttachment] })
assert.equal(attemptedGroupMove.status, 400)
assert.equal(database.prepare("SELECT message_id FROM attachments WHERE external_id = 'file-group'").get().message_id, groupMessage.id)

const conflictGroupAttachment = await uploadFile('file-group-conflict', groupBase.conversationExternalId, new Uint8Array([10, 11, 12]))
const conflictingGroup = await postGroupBackup({ ...groupBase, body: 'changed group text', attachments: [conflictGroupAttachment] })
assert.equal(conflictingGroup.status, 400)
assert.equal(database.prepare("SELECT message_id FROM attachments WHERE external_id = 'file-group-conflict'").get().message_id, null)
assert.equal(JSON.parse(database.prepare("SELECT metadata_json FROM messages WHERE external_id = 'message-group'").get().metadata_json).attachments.length, 1)

database.close()
console.log('Direct and group attachment backfill tests passed')
