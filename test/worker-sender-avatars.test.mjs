import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { DatabaseSync } from 'node:sqlite'
import worker from '../cloudflare-worker/worker/index.js'

const database = new DatabaseSync(':memory:')
database.exec(readFileSync(new URL('../cloudflare-worker/worker/schema.sql', import.meta.url), 'utf8'))
const stamp = '2026-10-07T12:00:00.000Z'
const connectorA = 'connector:avatar-a'
const connectorB = 'connector:avatar-b'
const tokenA = 'a'.repeat(40)
const tokenB = 'b'.repeat(40)
for (const [connectorId, account, display, token] of [
  [connectorA, 'a', 'Account A', tokenA], [connectorB, 'b', 'Account B', tokenB],
]) {
  database.prepare(`
    INSERT INTO connector_instances (
      id, kind, account_label, display_name, mode, state, capabilities_json, last_seen_at,
      created_at, updated_at
    ) VALUES (?, 'im', ?, ?, 'device_relay', 'online', '["receive_text"]', ?, ?, ?)
  `).run(connectorId, account, display, stamp, stamp, stamp)
  database.prepare(`
    INSERT INTO conversations (id, connector_id, external_id, title, created_at, updated_at)
    VALUES (?, ?, 'external-direct', 'Direct', ?, ?)
  `).run(`conversation-${account}`, connectorId, stamp, stamp)
  database.prepare(`
    INSERT INTO messages (
      id, conversation_id, connector_id, external_id, direction, sender_id, sender_name,
      body, content_type, delivery_state, queue_class, metadata_json, occurred_at, created_at
    ) VALUES (?, ?, ?, ?, 'inbound', 'sender:shared', 'Sender', ?, 'text', 'received',
      'immediate', '{}', ?, ?)
  `).run(`message-${account}`, `conversation-${account}`, connectorId, `event-${account}`,
    `body-${account}`, stamp, stamp)
}
database.prepare(`
  INSERT INTO messages (
    id, conversation_id, connector_id, external_id, direction, sender_id, sender_name,
    body, content_type, delivery_state, queue_class, metadata_json, occurred_at, created_at
  ) VALUES ('message-no-avatar', 'conversation-a', ?, 'event-no-avatar', 'inbound',
    'sender-no-avatar', 'Other', 'no image', 'text', 'received', 'immediate', '{}', ?, ?)
`).run(connectorA, stamp, stamp)

const objects = new Map()
const env = {
  ADMIN_TOKEN: 'z'.repeat(40),
  CONNECTOR_TOKENS: JSON.stringify({ [connectorA]: tokenA, [connectorB]: tokenB }),
  DB: {
    prepare(sql) {
      let args = []
      return {
        bind(...values) { args = values; return this },
        async first() { return database.prepare(sql).get(...args) ?? null },
        async all() { return { results: database.prepare(sql).all(...args) } },
        async run() {
          const result = database.prepare(sql).run(...args)
          return { meta: { changes: Number(result.changes) } }
        },
      }
    },
  },
  FILES: {
    async put(key, value, options) {
      const bytes = new Uint8Array(await new Response(value).arrayBuffer())
      objects.set(key, { bytes, options, httpEtag: `"${key}"` })
      return { size: bytes.length }
    },
    async head(key) {
      const value = objects.get(key)
      return value ? { size: value.bytes.length } : null
    },
    async get(key) {
      const value = objects.get(key)
      return value ? { body: new Blob([value.bytes]).stream(), httpEtag: value.httpEtag } : null
    },
    async delete(key) { objects.delete(key) },
  },
}

async function digest(bytes) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
    .map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

async function putAvatar(connectorId, token, senderId, bytes, sha, announced = bytes.length) {
  if (sha === undefined) sha = await digest(bytes)
  return worker.fetch(new Request(`https://message.example.com/api/connectors/sender-avatars/${senderId}`, {
    method: 'PUT',
    headers: {
      authorization: `Bearer ${token}`,
      'x-connector-id': connectorId,
      'content-type': 'image/png',
      'content-length': String(announced),
      'x-content-sha256': sha,
    },
    body: bytes,
  }), env, { waitUntil(promise) { promise.catch(() => {}) } })
}

const pngA = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1])
const pngB = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 2])
const unauthorized = await putAvatar(connectorA, tokenB, 'sender:shared', pngA)
assert.equal(unauthorized.status, 401)
assert.equal(database.prepare('SELECT COUNT(*) AS count FROM sender_avatars').get().count, 0)

const badHash = await putAvatar(connectorA, tokenA, 'sender:shared', pngA, '0'.repeat(64))
assert.equal(badHash.status, 400)
assert.equal(database.prepare('SELECT COUNT(*) AS count FROM sender_avatars').get().count, 0)
const tooLarge = await putAvatar(connectorA, tokenA, 'sender:shared', new Uint8Array(), '0'.repeat(64), 128 * 1024 + 1)
assert.equal(tooLarge.status, 400)
assert.equal(database.prepare('SELECT COUNT(*) AS count FROM sender_avatars').get().count, 0)

assert.equal((await putAvatar(connectorA, tokenA, 'sender:shared', pngA)).status, 201)
assert.equal((await putAvatar(connectorB, tokenB, 'sender:shared', pngB)).status, 201)
const rows = database.prepare(`
  SELECT connector_id, object_key, sha256 FROM sender_avatars ORDER BY connector_id
`).all()
assert.equal(rows.length, 2)
assert.notEqual(rows[0].object_key, rows[1].object_key)
assert.notEqual(rows[0].sha256, rows[1].sha256)

const adminHeaders = { authorization: `Bearer ${env.ADMIN_TOKEN}` }
const inboxResponse = await worker.fetch(new Request(
  'https://message.example.com/api/inbox?conversationId=conversation-a', { headers: adminHeaders },
), env, {})
assert.equal(inboxResponse.status, 200)
const inbox = await inboxResponse.json()
assert.equal(inbox.messages.length, 2)
const avatarMessage = inbox.messages.find((message) => message.id === 'message-a')
assert.equal(avatarMessage.body, 'body-a')
assert.equal(avatarMessage.senderAvatarPath,
  `/api/sender-avatars/${connectorA}/sender:shared?v=${rows[0].sha256}`)
assert.equal(inbox.messages.find((message) => message.id === 'message-no-avatar').senderAvatarPath, null)
const noAvatarInboxResponse = await worker.fetch(new Request(
  'https://message.example.com/api/inbox?conversationId=conversation-b', { headers: adminHeaders },
), env, {})
assert.equal((await noAvatarInboxResponse.json()).messages[0].senderAvatarPath,
  `/api/sender-avatars/${connectorB}/sender:shared?v=${rows[1].sha256}`)

for (const [connectorId, conversationId, senderId, externalId] of [
  [connectorA, 'group-a', 'sender:shared', 'group-backup-a'],
  [connectorA, 'group-a', 'sender-no-avatar', 'group-backup-no-avatar'],
  [connectorB, 'group-b', 'sender:shared', 'group-backup-b'],
]) {
  database.prepare(`
    INSERT INTO group_text_backups (
      connector_id, conversation_external_id, conversation_title, external_id, sender_id,
      sender_name, body, placement, occurred_at, received_at
    ) VALUES (?, ?, 'Group', ?, ?, 'Sender', 'fixture', 'normal', ?, ?)
  `).run(connectorId, conversationId, externalId, senderId, stamp, stamp)
}
const groupBackupsAResponse = await worker.fetch(new Request(
  `https://message.example.com/api/group-text-backups?connectorId=${encodeURIComponent(connectorA)}`,
  { headers: adminHeaders },
), env, {})
assert.equal(groupBackupsAResponse.status, 200)
const groupBackupsA = await groupBackupsAResponse.json()
assert.equal(groupBackupsA.backups.find((backup) => backup.externalId === 'group-backup-a').senderAvatarPath,
  `/api/sender-avatars/${connectorA}/sender:shared?v=${rows[0].sha256}`)
assert.equal(groupBackupsA.backups.find((backup) => backup.externalId === 'group-backup-no-avatar').senderAvatarPath, null)
const groupBackupsBResponse = await worker.fetch(new Request(
  `https://message.example.com/api/group-text-backups?connectorId=${encodeURIComponent(connectorB)}`,
  { headers: adminHeaders },
), env, {})
assert.equal((await groupBackupsBResponse.json()).backups[0].senderAvatarPath,
  `/api/sender-avatars/${connectorB}/sender:shared?v=${rows[1].sha256}`)

const download = await worker.fetch(new Request(
  `https://message.example.com/api/sender-avatars/${connectorA}/sender:shared`,
  { headers: adminHeaders },
), env, {})
assert.equal(download.status, 200)
assert.equal(download.headers.get('cache-control'), 'private, max-age=300')
assert.equal(download.headers.get('etag'), `"${rows[0].sha256}"`)
assert.deepEqual(new Uint8Array(await download.arrayBuffer()), pngA)
const connectorBDownload = await worker.fetch(new Request(
  `https://message.example.com/api/sender-avatars/${connectorB}/sender:shared`,
  { headers: adminHeaders },
), env, {})
assert.deepEqual(new Uint8Array(await connectorBDownload.arrayBuffer()), pngB)
const notModified = await worker.fetch(new Request(
  `https://message.example.com/api/sender-avatars/${connectorA}/sender:shared`,
  { headers: { ...adminHeaders, 'if-none-match': `"${rows[0].sha256}"` } },
), env, {})
assert.equal(notModified.status, 304)
const unauthenticatedDownload = await worker.fetch(new Request(
  `https://message.example.com/api/sender-avatars/${connectorA}/sender:shared`,
), env, {})
assert.equal(unauthenticatedDownload.status, 401)

database.close()
console.log('Sender avatar API, connector isolation, inbox, and group backup tests passed')
