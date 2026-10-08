import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { DatabaseSync } from 'node:sqlite'
import test from 'node:test'
import worker from '../cloudflare-worker/worker/index.js'
import {
  CONVERSATION_PAGE_SIZE,
  filterConversations,
  conversationPageCount,
  nextConversationPage,
  pageConversations,
} from '../cloudflare-worker/ui/src/conversation-list.mjs'

const stamp = '2026-10-07T12:00:00.000Z'
const database = new DatabaseSync(':memory:')
database.exec(readFileSync(new URL('../cloudflare-worker/worker/schema.sql', import.meta.url), 'utf8'))
database.prepare(`
  INSERT INTO connector_instances (
    id, kind, account_label, display_name, mode, state, capabilities_json,
    last_seen_at, created_at, updated_at
  ) VALUES ('wechat-fixture', 'im', 'work', 'WeChat', 'device_relay', 'online',
    '["receive_text"]', ?, ?, ?)
`).run(stamp, stamp, stamp)

const insertConversation = database.prepare(`
  INSERT INTO conversations (
    id, connector_id, external_id, title, last_message_at, created_at, updated_at
  ) VALUES (?, 'wechat-fixture', ?, ?, ?, ?, ?)
`)
const insertProfile = database.prepare(`
  INSERT INTO conversation_profiles (
    connector_id, conversation_external_id, display_name, conversation_type, placement, updated_at
  ) VALUES ('wechat-fixture', ?, ?, 'group', 'normal', ?)
`)
const origin = Date.UTC(2026, 0, 1)
for (let index = 0; index < 513; index += 1) {
  const externalId = `group-${String(index).padStart(3, '0')}`
  const conversationId = `conversation-${String(index).padStart(3, '0')}`
  const created = new Date(origin + index * 1000).toISOString()
  const title = index === 1 ? 'Last WeChat Group' : `WeChat Group ${index}`
  insertConversation.run(conversationId, externalId, title, created, created, stamp)
  insertProfile.run(externalId, title, stamp)
}

function d1Statement(sql, args = []) {
  return {
    bind(...values) { return d1Statement(sql, values) },
    async all() { return { results: database.prepare(sql).all(...args) } },
    async first() { return database.prepare(sql).get(...args) ?? null },
  }
}

const adminToken = 'a'.repeat(40)
const env = { ADMIN_TOKEN: adminToken, DB: { prepare: (sql) => d1Statement(sql) } }

test('Worker returns a bounded 512 conversations and UI can display or search the tail', async () => {
  const response = await worker.fetch(new Request('https://message.example.com/api/inbox', {
    headers: { authorization: `Bearer ${adminToken}` },
  }), env, {})
  assert.equal(response.status, 200)
  const inbox = await response.json()
  assert.equal(inbox.conversations.length, 512)
  assert.equal(inbox.conversations.at(-1).title, 'Last WeChat Group')

  const firstWindow = pageConversations(inbox.conversations)
  assert.equal(firstWindow.length, CONVERSATION_PAGE_SIZE)
  assert.equal(firstWindow.some((conversation) => conversation.title === 'Last WeChat Group'), false)
  const pages = conversationPageCount(inbox.conversations.length)
  assert.equal(pages, 6)
  let page = 0
  while (page < pages - 1) page = nextConversationPage(page, inbox.conversations.length)
  const lastPage = pageConversations(inbox.conversations, page)
  assert.equal(lastPage.length, 12)
  assert.equal(lastPage.at(-1).title, 'Last WeChat Group')
  assert.equal(lastPage.length <= CONVERSATION_PAGE_SIZE, true)

  const matches = filterConversations(inbox.conversations, { query: 'Last WeChat Group' })
  assert.equal(matches.length, 1)
  assert.equal(pageConversations(matches, 0)[0].id, inbox.conversations.at(-1).id)
})

test('conversation cap is separate from the unchanged 300-message cap', () => {
  const source = readFileSync(new URL('../cloudflare-worker/worker/index.js', import.meta.url), 'utf8')
  assert.match(source, /ORDER BY COALESCE\(p\.is_pinned, 0\) DESC, COALESCE\(c\.last_message_at, c\.created_at\) DESC LIMIT 512/)
  assert.equal((source.match(/ORDER BY occurred_at DESC, created_at DESC LIMIT 300/g) || []).length, 2)
})


test.after(() => database.close())
