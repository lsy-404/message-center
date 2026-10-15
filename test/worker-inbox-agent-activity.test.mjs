import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { DatabaseSync } from 'node:sqlite'
import worker from '../cloudflare-worker/worker/index.js'
import { createAdminTestAuth } from './helpers/oidc-fixture.mjs'

const database = new DatabaseSync(':memory:')
database.exec(readFileSync(new URL('../cloudflare-worker/worker/schema.sql', import.meta.url), 'utf8'))
const stamp = '2026-10-15T12:00:00.000Z'
database.prepare(`
  INSERT INTO connector_instances (
    id, kind, account_label, display_name, mode, state, capabilities_json, last_seen_at,
    created_at, updated_at
  ) VALUES ('connector:agent-activity', 'im', 'a', 'Account', 'cloud_relay', 'online',
    '["receive_text","send_text"]', ?, ?, ?)
`).run(stamp, stamp, stamp)
database.prepare(`
  INSERT INTO conversations (id, connector_id, external_id, title, created_at, updated_at)
  VALUES ('conversation-agent', 'connector:agent-activity', 'external-direct', 'Direct', ?, ?)
`).run(stamp, stamp)

const insertMessage = database.prepare(`
  INSERT INTO messages (
    id, conversation_id, connector_id, external_id, direction, sender_id, sender_name, body,
    content_type, delivery_state, queue_class, metadata_json, occurred_at, created_by, created_at
  ) VALUES (?, 'conversation-agent', 'connector:agent-activity', ?, ?, ?, ?, ?, 'text', ?, ?, '{}', ?, ?, ?)
`)
const rows = [
  ['in-pending', 'event-1', 'inbound', 'contact', 'Contact', 'pending body', 'received', 'immediate', null],
  ['in-leased', 'event-2', 'inbound', 'contact', 'Contact', 'leased body', 'received', 'immediate', null],
  ['in-escalated', 'event-3', 'inbound', 'contact', 'Contact', 'escalated body', 'received', 'immediate', null],
  ['in-background', 'event-4', 'inbound', 'contact', 'Contact', 'group text', 'received', 'background', null],
  ['out-agent', null, 'outbound', 'agent:worker-1', 'Agent', 'agent reply', 'delivered', 'immediate', 'agent:worker-1'],
  ['out-owner', null, 'outbound', 'admin-subject', 'Owner', 'owner reply', 'queued', 'immediate', 'admin-subject'],
]
rows.forEach(([id, externalId, direction, senderId, senderName, body, deliveryState, queueClass, createdBy], index) => {
  const occurredAt = new Date(Date.parse(stamp) + index * 1000).toISOString()
  insertMessage.run(id, externalId, direction, senderId, senderName, body, deliveryState, queueClass,
    occurredAt, createdBy, occurredAt)
})
const insertQueue = database.prepare(`
  INSERT INTO agent_queue (message_id, state, created_at) VALUES (?, ?, ?)
`)
insertQueue.run('in-pending', 'pending', stamp)
insertQueue.run('in-leased', 'leased', stamp)
insertQueue.run('in-escalated', 'dead_letter', stamp)

const auth = await createAdminTestAuth({
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
})

const response = await worker.fetch(new Request(
  'https://message.example.com/api/inbox?conversationId=conversation-agent', { headers: auth.headers },
), auth.env, {})
assert.equal(response.status, 200)
const inbox = await response.json()
const byId = new Map(inbox.messages.map((message) => [message.id, message]))
assert.equal(inbox.messages.length, rows.length, 'agent queue join does not duplicate or drop messages')
assert.deepEqual(inbox.messages.map((message) => message.id), rows.map(([id]) => id), 'chronological order is unchanged')

assert.equal(byId.get('in-pending').agentRead, false, 'unclaimed queue entries are unread by the agent')
assert.equal(byId.get('in-leased').agentRead, true, 'a claimed message has been read by the agent')
assert.equal(byId.get('in-escalated').agentRead, true, 'a message handed to manual review was read by the agent')
assert.equal(byId.get('in-background').agentRead, null, 'background group text never reaches the agent queue')
assert.equal(byId.get('out-agent').agentRead, null)

assert.equal(byId.get('in-pending').authorRole, 'contact')
assert.equal(byId.get('out-agent').authorRole, 'agent', 'agent:* creators are reported as agent replies')
assert.equal(byId.get('out-owner').authorRole, 'owner', 'administrator sends are reported as owner replies')
for (const message of inbox.messages) {
  assert.equal('createdBy' in message, false, 'raw creator identities stay server-side')
  assert.equal('agentState' in message, false, 'queue internals stay server-side')
}
console.log('Inbox agent read fields passed.')
