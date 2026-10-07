import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { DatabaseSync } from 'node:sqlite'
import worker from '../cloudflare-worker/worker/index.js'

const database = new DatabaseSync(':memory:')
database.exec(readFileSync(new URL('../cloudflare-worker/worker/schema.sql', import.meta.url), 'utf8'))
const stamp = '2026-10-07T12:00:00.000Z'
const connectorId = 'connector-group-fixture'
const conversationId = 'conversation-group-fixture'
database.prepare(`
  INSERT INTO connector_instances (
    id, kind, account_label, display_name, mode, state, capabilities_json, last_seen_at,
    created_at, updated_at
  ) VALUES (?, 'im', 'fixture', 'Fixture', 'device_relay', 'online', '["receive_text"]', ?, ?, ?)
`).run(connectorId, stamp, stamp, stamp)
database.prepare(`
  INSERT INTO conversations (
    id, connector_id, external_id, title, created_at, updated_at
  ) VALUES (?, ?, ?, '测试群聊', ?, ?)
`).run(conversationId, connectorId, 'external-group', stamp, stamp)
database.prepare(`
  INSERT INTO conversation_profiles (
    connector_id, conversation_external_id, display_name, conversation_type, placement, updated_at
  ) VALUES (?, 'external-group', '测试群聊', 'group', 'normal', ?)
`).run(connectorId, stamp)

const insertMessage = database.prepare(`
  INSERT INTO messages (
    id, conversation_id, connector_id, external_id, direction, sender_name, body, content_type,
    delivery_state, queue_class, metadata_json, occurred_at, created_at
  ) VALUES (?, ?, ?, ?, 'inbound', ?, ?, 'text', 'received', 'background', ?, ?, ?)
`)
const insertAttachment = database.prepare(`
  INSERT INTO attachments (
    id, message_id, connector_id, object_key, file_name, mime_type, size_bytes, sha256, state, created_at
  ) VALUES (?, ?, ?, ?, ?, ?, 4, ?, 'uploaded_inbound', ?)
`)
const pngBytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47])
const objects = new Map()
for (let index = 0; index < 125; index += 1) {
  const suffix = String(index).padStart(3, '0')
  const messageId = `message-group-${suffix}`
  const fileId = `file-group-${suffix}`
  const objectKey = `fixture/${fileId}`
  insertMessage.run(messageId, conversationId, connectorId, `external-${suffix}`, `成员${suffix}`,
    `群聊消息 ${suffix}`, JSON.stringify({ conversationType: 'group' }), stamp, stamp)
  insertAttachment.run(fileId, messageId, connectorId, objectKey, `图片${suffix}.png`, 'image/png', 'a'.repeat(64), stamp)
  objects.set(objectKey, pngBytes)
}
insertAttachment.run('file-pdf-fixture', 'message-group-000', connectorId, 'fixture/document',
  'document.pdf', 'application/pdf', 'b'.repeat(64), stamp)
objects.set('fixture/document', new Uint8Array([0x25, 0x50, 0x44, 0x46]))

function d1Statement(sql, args = []) {
  return {
    bind(...values) {
      if (values.length > 100) throw new Error('D1_ERROR: too many SQL variables')
      return d1Statement(sql, values)
    },
    async all() { return { results: database.prepare(sql).all(...args) } },
    async first() { return database.prepare(sql).get(...args) ?? null },
  }
}

const adminToken = 'a'.repeat(40)
const env = {
  ADMIN_TOKEN: adminToken,
  DB: { prepare: (sql) => d1Statement(sql) },
  FILES: {
    async get(key) {
      const body = objects.get(key)
      return body ? { body, size: body.byteLength, httpEtag: `etag-${key}` } : null
    },
  },
}
const inboxResponse = await worker.fetch(new Request(
  `https://message.example.com/api/inbox?conversationId=${conversationId}`,
  { headers: { authorization: `Bearer ${adminToken}` } },
), env, {})
assert.equal(inboxResponse.status, 200)
assert.match(inboxResponse.headers.get('content-type'), /application\/json; charset=utf-8/)
const inbox = await inboxResponse.json()
assert.equal(inbox.messages.length, 125)
assert.ok(inbox.messages.every((message) => message.body.startsWith('群聊消息 ')))
assert.ok(inbox.messages.every((message) => message.attachments.length >= 1))
assert.equal(inbox.messages.find((message) => message.id === 'message-group-000').attachments.length, 2)

const imageResponse = await worker.fetch(new Request(
  'https://message.example.com/api/files/file-group-000',
  { headers: { authorization: `Bearer ${adminToken}` } },
), env, {})
assert.equal(imageResponse.status, 200)
assert.equal(imageResponse.headers.get('content-disposition')?.split(';')[0], 'inline')
assert.equal(imageResponse.headers.get('content-type'), 'image/png')

const documentResponse = await worker.fetch(new Request(
  'https://message.example.com/api/files/file-pdf-fixture',
  { headers: { authorization: `Bearer ${adminToken}` } },
), env, {})
assert.equal(documentResponse.status, 200)
assert.equal(documentResponse.headers.get('content-disposition')?.split(';')[0], 'attachment')

database.close()
console.log('Large group inbox and inline image tests passed')
