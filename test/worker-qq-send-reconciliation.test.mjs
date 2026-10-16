import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import worker from '../cloudflare-worker/worker/index.js';
import { createAdminTestAuth } from './helpers/oidc-fixture.mjs';

const stamp = new Date().toISOString();
const connectorId = 'instance-qq-reconcile';
const connectorToken = 'q'.repeat(40);
const genericConnectorId = 'instance-generic-reconcile';
const genericConnectorToken = 'g'.repeat(40);
const conversationRowId = 'conversation-qq-reconcile';
const genericConversationRowId = 'conversation-generic-reconcile';
const database = new DatabaseSync(':memory:');
database.exec(readFileSync(new URL('../cloudflare-worker/worker/schema.sql', import.meta.url), 'utf8'));
database.prepare(`INSERT INTO connector_instances
  (id, kind, account_label, display_name, mode, capabilities_json, created_at, updated_at)
  VALUES (?, 'qq', 'primary', 'QQ', 'device_relay', '["receive_text","send_text"]', ?, ?)`)
  .run(connectorId, stamp, stamp);
database.prepare(`INSERT INTO connector_instances
  (id, kind, account_label, display_name, mode, capabilities_json, created_at, updated_at)
  VALUES (?, 'wechat', 'primary', 'WeChat', 'device_relay', '["receive_text","send_text"]', ?, ?)`)
  .run(genericConnectorId, stamp, stamp);

function d1Statement(sql, args = []) {
  const statement = database.prepare(sql);
  return {
    bind(...values) { return d1Statement(sql, values); },
    async run() { const result = statement.run(...args); return { meta: { changes: Number(result.changes) } }; },
    async first() { return statement.get(...args) ?? null; },
    async all() { return { results: statement.all(...args) }; },
  };
}

const d1 = {
  prepare(sql) { return d1Statement(sql); },
  async batch(statements) {
    database.exec('BEGIN IMMEDIATE');
    try {
      const results = [];
      for (const statement of statements) results.push(await statement.run());
      database.exec('COMMIT');
      return results;
    } catch (error) {
      database.exec('ROLLBACK');
      throw error;
    }
  },
};

const auth = await createAdminTestAuth({
  DB: d1,
  FILES: { async put() {}, async delete() {}, async head() { return null; }, async get() { return null; }, async list() { return { objects: [], truncated: false }; } },
  CONNECTOR_TOKENS: JSON.stringify({ [connectorId]: connectorToken, [genericConnectorId]: genericConnectorToken }),
});
const env = auth.env;
function headersFor(id) {
  const token = id === connectorId ? connectorToken : genericConnectorToken;
  return { authorization: `Bearer ${token}`, 'content-type': 'application/json', 'x-connector-id': id };
}
const headers = headersFor(connectorId);
const conversationExternalId = 'primary:conversation-aaaaaaaa';
database.prepare(`INSERT INTO conversations (id, connector_id, external_id, title, created_at, updated_at)
  VALUES (?, ?, ?, 'Test QQ', ?, ?)`)
  .run(conversationRowId, connectorId, conversationExternalId, stamp, stamp);
const genericConversationExternalId = 'primary:conversation-bbbbbbbb';
database.prepare(`INSERT INTO conversations (id, connector_id, external_id, title, created_at, updated_at)
  VALUES (?, ?, ?, 'Test generic', ?, ?)`)
  .run(genericConversationRowId, genericConnectorId, genericConversationExternalId, stamp, stamp);

function qqIdentity(sourceId) {
  let hash = 0x811c9dc5;
  for (const character of sourceId) hash = Math.imul(hash ^ character.charCodeAt(0), 0x01000193) >>> 0;
  const alias = `message-${hash.toString(16).padStart(8, '0')}`;
  return { externalId: `primary:qq-message:${sourceId}`, receipt: JSON.stringify({ sourceId, messageAlias: alias,
    messageType: 1, sendStatus: 2, confirmation: 'verified-status' }) };
}

function seedCommand(suffix, body = 'same outbound body', options = {}) {
  const commandConnectorId = options.connectorId || connectorId;
  const conversationId = options.conversationId || conversationRowId;
  const messageId = `message-${suffix}`;
  const commandId = `command-${suffix}`;
  database.prepare(`INSERT INTO messages (id, conversation_id, connector_id, direction, sender_name, body,
    content_type, delivery_state, occurred_at, created_by, created_at)
    VALUES (?, ?, ?, 'outbound', 'Administrator', ?, 'text', 'queued', ?, 'admin:test', ?)`)
    .run(messageId, conversationId, commandConnectorId, body, stamp, stamp);
  database.prepare(`INSERT INTO commands (id, connector_id, conversation_id, message_id, kind, payload_json,
    state, idempotency_key, lease_token, lease_expires_at, attempts, created_by, created_at)
    VALUES (?, ?, ?, ?, 'send_text', ?, 'leased', ?, ?, '2999-01-01T00:00:00.000Z', 1, 'admin:test', ?)`)
    .run(commandId, commandConnectorId, conversationId, messageId, JSON.stringify({ body }),
      `idempotency-${suffix}`, `lease-${suffix}`, stamp);
  return { connectorId: commandConnectorId, conversationId, messageId, commandId, leaseToken: `lease-${suffix}`, body };
}

async function complete(command, sourceId = '9007199254740993', overrides = {}) {
  const identity = typeof sourceId === 'string' ? qqIdentity(sourceId) : sourceId;
  return worker.fetch(new Request(`https://message.example.com/api/connectors/commands/${command.commandId}/complete`, {
    method: 'POST',
    headers: headersFor(command.connectorId),
    body: JSON.stringify({ connectorId: command.connectorId, leaseToken: command.leaseToken,
      ok: true, result: identity, ...overrides }),
  }), env, {});
}

function selfEvent(sourceId = '9007199254740993', options = {}) {
  const identity = qqIdentity(sourceId);
  return {
    externalId: options.externalId || identity.externalId,
    conversationExternalId: options.conversationExternalId || conversationExternalId,
    conversationTitle: 'Test QQ',
    senderName: 'Me',
    occurredAt: stamp,
    body: options.body || 'same outbound body',
    contentType: 'text',
    conversationType: options.conversationType || 'direct',
    trigger: options.trigger || 'direct',
    isSelf: options.isSelf ?? true,
    attachments: [],
  };
}

async function ingest(messages) {
  return worker.fetch(new Request('https://message.example.com/api/connectors/events', {
    method: 'POST', headers, body: JSON.stringify({ connectorId, messages }),
  }), env, {});
}

const receiptFirst = seedCommand('receipt-first');
const receiptFirstAck = await complete(receiptFirst);
assert.equal(receiptFirstAck.status, 200);
const receiptFirstId = qqIdentity('9007199254740993').externalId;
assert.equal(database.prepare('SELECT external_id FROM messages WHERE id = ?').get(receiptFirst.messageId).external_id, receiptFirstId);
assert.equal((await ingest([selfEvent()])).status, 200);
assert.equal(database.prepare('SELECT COUNT(*) AS n FROM messages WHERE connector_id = ? AND external_id = ?')
  .get(connectorId, receiptFirstId).n, 1);
assert.equal(database.prepare('SELECT direction, delivery_state FROM messages WHERE id = ?')
  .get(receiptFirst.messageId).direction, 'outbound');
assert.equal(database.prepare('SELECT COUNT(*) AS n FROM agent_queue q JOIN messages m ON m.id = q.message_id WHERE m.external_id = ?')
  .get(receiptFirstId).n, 0);
const wrongDirectionEvent = await ingest([selfEvent('9007199254740993', { isSelf: false })]);
assert.equal(wrongDirectionEvent.status, 400);
assert.equal(database.prepare('SELECT direction FROM messages WHERE id = ?').get(receiptFirst.messageId).direction, 'outbound');
assert.equal((await complete(receiptFirst)).status, 400);

const eventFirst = seedCommand('event-first');
const eventFirstId = qqIdentity('9007199254740994').externalId;
assert.equal((await ingest([selfEvent('9007199254740994')])).status, 200);
const eventRowBeforeAck = database.prepare('SELECT id, direction, delivery_state FROM messages WHERE connector_id = ? AND external_id = ?')
  .get(connectorId, eventFirstId);
assert.equal(eventRowBeforeAck.direction, 'outbound');
assert.equal(eventRowBeforeAck.delivery_state, 'delivered');
assert.equal(database.prepare('SELECT COUNT(*) AS n FROM agent_queue WHERE message_id = ?').get(eventRowBeforeAck.id).n, 0);
const eventFirstAck = await complete(eventFirst, '9007199254740994');
assert.equal(eventFirstAck.status, 200);
assert.equal(database.prepare('SELECT message_id, state FROM commands WHERE id = ?').get(eventFirst.commandId).message_id, eventRowBeforeAck.id);
assert.equal(database.prepare('SELECT COUNT(*) AS n FROM messages WHERE id IN (?, ?)')
  .get(eventFirst.messageId, eventRowBeforeAck.id).n, 1);
assert.equal(database.prepare('SELECT created_by, delivery_state FROM messages WHERE id = ?')
  .get(eventRowBeforeAck.id).created_by, 'admin:test');

const racedAck = seedCommand('event-insert-race', 'race outbound body');
const racedIdentity = qqIdentity('9007199254741000');
const originalBatch = d1.batch;
let insertEventBetweenReadAndBatch = true;
d1.batch = async (statements) => {
  if (insertEventBetweenReadAndBatch) {
    insertEventBetweenReadAndBatch = false;
    database.prepare(`INSERT INTO messages
      (id, conversation_id, connector_id, external_id, direction, sender_name, body,
       content_type, delivery_state, queue_class, metadata_json, occurred_at, created_at)
      VALUES (?, ?, ?, ?, 'outbound', 'Me', ?, 'text', 'delivered', 'immediate', ?, ?, ?)`)
      .run('message-raced-native-event', racedAck.conversationId, connectorId, racedIdentity.externalId,
        racedAck.body, JSON.stringify({ isSelf: true }), stamp, stamp);
  }
  try {
    return await originalBatch(statements);
  } catch (error) {
    if (String(error?.message || '').includes('UNIQUE constraint failed: messages.connector_id, messages.external_id')) {
      throw new Error(`D1_ERROR: ${error.message}: SQLITE_CONSTRAINT`);
    }
    throw error;
  }
};
try {
  const firstRaceAck = await complete(racedAck, '9007199254741000');
  assert.equal(firstRaceAck.status, 200);
  assert.equal((await firstRaceAck.json()).state, 'completed');
  assert.equal(database.prepare('SELECT state, message_id FROM commands WHERE id = ?')
    .get(racedAck.commandId).message_id, 'message-raced-native-event');
  assert.equal(database.prepare('SELECT COUNT(*) AS n FROM messages WHERE connector_id = ? AND external_id = ?')
    .get(connectorId, racedIdentity.externalId).n, 1);
  const replayAck = await complete(racedAck, '9007199254741000');
  assert.equal(replayAck.status, 400);
  assert.equal(database.prepare('SELECT COUNT(*) AS n FROM messages WHERE connector_id = ? AND external_id = ?')
    .get(connectorId, racedIdentity.externalId).n, 1);
  assert.equal(database.prepare('SELECT message_id FROM commands WHERE id = ?').get(racedAck.commandId).message_id,
    'message-raced-native-event');
  assert.equal(database.prepare('SELECT 1 FROM messages WHERE id = ?').get(racedAck.messageId), undefined);
} finally {
  d1.batch = originalBatch;
}

const sameTextOtherId = qqIdentity('9007199254740995').externalId;
assert.equal((await ingest([selfEvent('9007199254740995')])).status, 200);
assert.equal(database.prepare('SELECT COUNT(*) AS n FROM messages WHERE connector_id = ? AND body = ?')
  .get(connectorId, 'same outbound body').n, 3);

const collisionA = qqIdentity('2328622970');
const collisionB = qqIdentity('2948735191');
assert.equal(JSON.parse(collisionA.receipt).messageAlias, JSON.parse(collisionB.receipt).messageAlias);
assert.notEqual(collisionA.externalId, collisionB.externalId);
assert.equal((await ingest([selfEvent('2328622970', { body: 'same collision body' }),
  selfEvent('2948735191', { body: 'same collision body' })])).status, 200);
assert.equal(database.prepare('SELECT COUNT(*) AS n FROM messages WHERE connector_id = ? AND body = ?')
  .get(connectorId, 'same collision body').n, 2);
assert.equal(database.prepare('SELECT COUNT(DISTINCT external_id) AS n FROM messages WHERE connector_id = ? AND body = ?')
  .get(connectorId, 'same collision body').n, 2);

const unsafeMatch = seedCommand('unsafe-match');
const unsafeId = qqIdentity('9007199254740996').externalId;
assert.equal((await ingest([selfEvent('9007199254740996', { body: 'different body' })])).status, 200);
const unsafeAck = await complete(unsafeMatch, '9007199254740996');
assert.equal(unsafeAck.status, 200);
assert.equal((await unsafeAck.json()).state, 'manual_review');
assert.equal(database.prepare('SELECT COUNT(*) AS n FROM messages WHERE connector_id = ? AND external_id = ?')
  .get(connectorId, unsafeId).n, 1);
assert.ok(database.prepare('SELECT 1 FROM messages WHERE id = ?').get(unsafeMatch.messageId));

const malformed = seedCommand('malformed-receipt');
const malformedIdentity = qqIdentity('9007199254740997');
const malformedAck = await complete(malformed, { ...malformedIdentity, externalId: 'primary:message-00000000' });
assert.equal(malformedAck.status, 200);
assert.equal((await malformedAck.json()).state, 'manual_review');
assert.equal(database.prepare('SELECT external_id, delivery_state FROM messages WHERE id = ?').get(malformed.messageId).external_id, null);

const missingQQReceipt = seedCommand('missing-qq-receipt');
const missingQQAck = await complete(missingQQReceipt, {});
assert.equal(missingQQAck.status, 200);
assert.equal((await missingQQAck.json()).state, 'manual_review');
assert.equal(database.prepare('SELECT delivery_state, external_id FROM messages WHERE id = ?')
  .get(missingQQReceipt.messageId).delivery_state, 'uncertain');

const contradictoryQQRetry = seedCommand('contradictory-qq-retry');
const contradictoryQQAck = await complete(contradictoryQQRetry, '9007199254741010', { retry: true });
assert.equal(contradictoryQQAck.status, 200);
assert.equal((await contradictoryQQAck.json()).state, 'manual_review');
assert.equal(database.prepare('SELECT state FROM commands WHERE id = ?').get(contradictoryQQRetry.commandId).state, 'manual_review');
assert.equal(database.prepare('SELECT delivery_state, external_id FROM messages WHERE id = ?')
  .get(contradictoryQQRetry.messageId).delivery_state, 'uncertain');

const dispatchedQQRetry = seedCommand('dispatched-qq-retry');
const dispatchedQQAck = await complete(dispatchedQQRetry, {}, {
  retry: true, ok: false, result: { dispatched: true },
});
assert.equal(dispatchedQQAck.status, 200);
assert.equal((await dispatchedQQAck.json()).state, 'manual_review');

const uncertainQQRetry = seedCommand('uncertain-qq-retry');
const uncertainQQAck = await complete(uncertainQQRetry, {}, {
  retry: true, ok: false, uncertain: true, result: { dispatched: false },
});
assert.equal(uncertainQQAck.status, 200);
assert.equal((await uncertainQQAck.json()).state, 'manual_review');

const genuineQQRetry = seedCommand('genuine-qq-retry');
const genuineQQAck = await complete(genuineQQRetry, {}, {
  retry: true, ok: false, result: { dispatched: false, retryable: true },
});
assert.equal(genuineQQAck.status, 200);
assert.equal((await genuineQQAck.json()).state, 'pending');
assert.equal(database.prepare('SELECT state FROM commands WHERE id = ?').get(genuineQQRetry.commandId).state, 'pending');
assert.equal(database.prepare('SELECT delivery_state, external_id FROM messages WHERE id = ?')
  .get(genuineQQRetry.messageId).delivery_state, 'queued');

const genericCommand = seedCommand('generic-receipt', 'generic outbound body', {
  connectorId: genericConnectorId, conversationId: genericConversationRowId,
});
const genericAck = await worker.fetch(new Request(`https://message.example.com/api/connectors/commands/${genericCommand.commandId}/complete`, {
  method: 'POST', headers: headersFor(genericConnectorId),
  body: JSON.stringify({ connectorId: genericConnectorId, leaseToken: genericCommand.leaseToken,
    ok: true, result: { receipt: 'generic native receipt' } }),
}), env, {});
assert.equal(genericAck.status, 200);
assert.equal((await genericAck.json()).state, 'completed');
assert.equal(database.prepare('SELECT external_id, delivery_state FROM messages WHERE id = ?')
  .get(genericCommand.messageId).delivery_state, 'delivered');
assert.equal(database.prepare('SELECT external_id FROM messages WHERE id = ?')
  .get(genericCommand.messageId).external_id, null);

const wrongTarget = seedCommand('wrong-target');
const wrongTargetIdentity = qqIdentity('9007199254740999');
assert.equal((await ingest([selfEvent('9007199254740999', {
  conversationExternalId: 'primary:conversation-bbbbbbbb',
})])).status, 200);
const wrongTargetAck = await complete(wrongTarget, '9007199254740999');
assert.equal((await wrongTargetAck.json()).state, 'manual_review');
assert.ok(database.prepare('SELECT 1 FROM messages WHERE id = ?').get(wrongTarget.messageId));
assert.equal(database.prepare('SELECT conversation_id FROM messages WHERE connector_id = ? AND external_id = ?')
  .get(connectorId, wrongTargetIdentity.externalId).conversation_id === wrongTarget.conversationId, false);

const groupSelf = seedCommand('group-self');
assert.equal((await ingest([selfEvent('9007199254740998', { conversationType: 'group', trigger: 'background' })])).status, 200);
assert.equal(database.prepare('SELECT COUNT(*) AS n FROM messages WHERE connector_id = ? AND external_id = ?')
  .get(connectorId, qqIdentity('9007199254740998').externalId).n, 1);

database.close();
console.log('QQ send reconciliation receipt-first/event-first SQLite checks passed');
