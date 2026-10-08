import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';
import worker from '../cloudflare-worker/worker/index.js';

const connectorId = 'connector-review-a';
const otherConnectorId = 'connector-review-b';
const connectorToken = 'c'.repeat(40);
const stamp = '2026-10-07T12:00:00.000Z';

function createHarness() {
  const database = new DatabaseSync(':memory:');
  database.exec(readFileSync(new URL('../cloudflare-worker/worker/schema.sql', import.meta.url), 'utf8'));

  let batchTail = Promise.resolve();
  let afterBatchCommit = null;
  function serialize(operation) {
    const run = batchTail.then(operation);
    batchTail = run.catch(() => {});
    return run;
  }

  function statementFor(sql, values = []) {
    const statement = database.prepare(sql);
    return {
      bind(...args) { return statementFor(sql, args); },
      async run() { return serialize(() => this.runInBatch()); },
      runInBatch() {
        const result = statement.run(...values);
        return { meta: { changes: Number(result.changes) } };
      },
      async first() { return serialize(() => statement.get(...values) ?? null); },
      async all() { return serialize(() => ({ results: statement.all(...values) })); },
    };
  }

  const DB = {
    prepare(sql) { return statementFor(sql); },
    batch(statements) { return serialize(() => {
        database.exec('BEGIN IMMEDIATE');
        try {
          const results = statements.map((statement) => statement.runInBatch());
          database.exec('COMMIT');
          if (afterBatchCommit) {
            const hook = afterBatchCommit;
            afterBatchCommit = null;
            hook();
          }
          return results;
        } catch (error) {
          database.exec('ROLLBACK');
          throw error;
        }
      });
    },
  };

  const env = { DB, CONNECTOR_TOKENS: JSON.stringify({ [connectorId]: connectorToken }) };
  const ctx = {};
  return { database, env, ctx, setAfterBatchCommit(hook) { afterBatchCommit = hook; } };
}

function seedConnector(database, id, capabilities) {
  database.prepare(`
    INSERT INTO connector_instances (
      id, kind, account_label, display_name, mode, capabilities_json, created_at, updated_at
    ) VALUES (?, 'im', 'fixture', 'Fixture', 'device_relay', ?, ?, ?)
  `).run(id, JSON.stringify(capabilities), stamp, stamp);
  const conversationId = `conversation-${id}`;
  database.prepare(`
    INSERT INTO conversations (id, connector_id, external_id, title, created_at, updated_at)
    VALUES (?, ?, ?, 'Fixture', ?, ?)
  `).run(conversationId, id, `native-${id}`, stamp, stamp);
  return conversationId;
}

function seedMessageAndCommand(database, conversationId, connector, suffix, state,
  leaseExpiresAt = null, resultJson = null) {
  const messageId = `message-${suffix}`;
  const commandId = `command-${suffix}`;
  database.prepare(`
    INSERT INTO messages (
      id, conversation_id, connector_id, direction, sender_name, body,
      delivery_state, occurred_at, created_at
    ) VALUES (?, ?, ?, 'outbound', 'Administrator', ?, 'queued', ?, ?)
  `).run(messageId, conversationId, connector, `body-${suffix}`, stamp, stamp);
  const payload = JSON.stringify({ body: `payload-${suffix}` });
  database.prepare(`
    INSERT INTO commands (
      id, connector_id, conversation_id, message_id, kind, payload_json, state,
      idempotency_key, lease_token, lease_expires_at, attempts, result_json, created_by, created_at
    ) VALUES (?, ?, ?, ?, 'send_text', ?, ?, ?, ?, ?, 1, ?, 'admin:token', ?)
  `).run(commandId, connector, conversationId, messageId, payload, state,
    `idempotency-${suffix}`, state === 'leased' ? `lease-${suffix}` : null,
    leaseExpiresAt, resultJson, stamp);
  return { messageId, commandId, payload };
}

async function register(harness, capabilities = ['receive_text', 'send_text']) {
  return worker.fetch(new Request('https://message.example.com/api/connectors/register', {
    method: 'POST',
    headers: {
      authorization: `Bearer ${connectorToken}`,
      'content-type': 'application/json',
      'x-connector-id': connectorId,
    },
    body: JSON.stringify({
      id: connectorId, kind: 'im', accountLabel: 'Fixture', displayName: 'Fixture', capabilities,
    }),
  }), harness.env, harness.ctx);
}

test('enabling send_text quarantines preexisting pending and leased commands without deleting payloads', async () => {
  const harness = createHarness();
  const { database } = harness;
  const conversationId = seedConnector(database, connectorId, ['receive_text']);
  const otherConversationId = seedConnector(database, otherConnectorId, ['receive_text']);
  const pending = seedMessageAndCommand(database, conversationId, connectorId,
    'old-pending', 'pending');
  const expiredLease = seedMessageAndCommand(database, conversationId, connectorId,
    'old-expired', 'leased', '2020-01-01T00:00:00.000Z');
  const activeLease = seedMessageAndCommand(database, conversationId, connectorId,
    'old-active', 'leased', '2999-01-01T00:00:00.000Z');
  database.prepare(`
    INSERT INTO attachments (
      id, message_id, connector_id, file_name, mime_type, size_bytes, sha256, state, created_at
    ) VALUES ('attachment-old-pending', ?, ?, 'old.bin', 'application/octet-stream', 4, ?, 'queued', ?)
  `).run(pending.messageId, connectorId, '0'.repeat(64), stamp);
  const completed = seedMessageAndCommand(database, conversationId, connectorId,
    'completed', 'completed', null, '{"ok":true}');
  database.prepare("UPDATE messages SET delivery_state = 'delivered' WHERE id = ?")
    .run(completed.messageId);
  const priorReview = seedMessageAndCommand(database, conversationId, connectorId,
    'prior-review', 'manual_review', null, '{"error":"prior_review"}');
  const otherPending = seedMessageAndCommand(database, otherConversationId, otherConnectorId,
    'other-pending', 'pending');

  const response = await register(harness);
  assert.equal(response.status, 201);
  assert.deepEqual(
    JSON.parse(database.prepare('SELECT capabilities_json FROM connector_instances WHERE id = ?')
      .get(connectorId).capabilities_json), ['receive_text', 'send_text'],
  );

  const state = (commandId) => database.prepare(`
    SELECT state, payload_json, result_json, lease_token, lease_expires_at
    FROM commands WHERE id = ?
  `).get(commandId);
  const pendingResult = state(pending.commandId);
  assert.equal(pendingResult.state, 'manual_review');
  assert.equal(pendingResult.payload_json, pending.payload);
  assert.deepEqual(JSON.parse(pendingResult.result_json), {
    error: 'capability_enabled_old_command_review', dispatched: false,
    transitionId: JSON.parse(state(expiredLease.commandId).result_json).transitionId,
  });
  assert.equal(state(expiredLease.commandId).state, 'manual_review');
  assert.equal(state(activeLease.commandId).state, 'manual_review');
  assert.equal(state(expiredLease.commandId).lease_token, null);
  assert.equal(state(expiredLease.commandId).lease_expires_at, null);
  assert.equal(state(activeLease.commandId).lease_token, null);
  assert.equal(state(activeLease.commandId).lease_expires_at, null);
  assert.equal(JSON.parse(state(expiredLease.commandId).result_json).error,
    'capability_enabled_old_lease_review');
  assert.equal(JSON.parse(state(activeLease.commandId).result_json).error,
    'capability_enabled_old_lease_review');
  assert.equal(state(completed.commandId).state, 'completed');
  assert.equal(state(completed.commandId).result_json, '{"ok":true}');
  assert.equal(state(priorReview.commandId).result_json, '{"error":"prior_review"}');
  assert.equal(state(otherPending.commandId).state, 'pending');

  for (const message of [pending, expiredLease, activeLease]) {
    assert.equal(database.prepare('SELECT delivery_state FROM messages WHERE id = ?')
      .get(message.messageId).delivery_state, 'manual_review');
    assert.equal(database.prepare('SELECT body FROM messages WHERE id = ?')
      .get(message.messageId).body, `body-${message.commandId.slice('command-'.length)}`);
  }
  assert.equal(database.prepare('SELECT state FROM attachments WHERE id = ?')
    .get('attachment-old-pending').state, 'manual_review');
  assert.equal(database.prepare('SELECT delivery_state FROM messages WHERE id = ?')
    .get(completed.messageId).delivery_state, 'delivered');
  assert.equal(database.prepare(`
    SELECT COUNT(*) AS total FROM audit_log
    WHERE actor = ? AND action = 'connector_send_commands_manual_review'
  `).get(`connector:${connectorId}`).total, 1);
  const staleLeaseCompletion = await worker.fetch(new Request(
    `https://message.example.com/api/connectors/commands/${activeLease.commandId}/complete`, {
      method: 'POST',
      headers: {
        authorization: `Bearer ${connectorToken}`,
        'content-type': 'application/json',
        'x-connector-id': connectorId,
      },
      body: JSON.stringify({ connectorId, leaseToken: 'lease-old-active', ok: true }),
    }), harness.env, harness.ctx);
  assert.equal(staleLeaseCompletion.status, 400);
  assert.equal(database.prepare('SELECT state FROM commands WHERE id = ?')
    .get(activeLease.commandId).state, 'manual_review');
  harness.database.close();
});

test('repeated concurrent registration does not quarantine commands created after enable', async () => {
  const harness = createHarness();
  const { database } = harness;
  const conversationId = seedConnector(database, connectorId, ['receive_text']);
  const old = seedMessageAndCommand(database, conversationId, connectorId,
    'race-old', 'pending');
  let fresh;
  harness.setAfterBatchCommit(() => {
    fresh = seedMessageAndCommand(database, conversationId, connectorId,
      'race-fresh', 'pending');
  });

  const responses = await Promise.all([register(harness), register(harness)]);
  assert.deepEqual(responses.map((response) => response.status), [201, 201]);
  assert.equal(database.prepare('SELECT state FROM commands WHERE id = ?')
    .get(old.commandId).state, 'manual_review');
  assert.equal(database.prepare('SELECT state FROM commands WHERE id = ?')
    .get(fresh.commandId).state, 'pending');
  assert.equal(database.prepare(`
    SELECT COUNT(*) AS total FROM audit_log
    WHERE actor = ? AND action = 'connector_send_commands_manual_review'
  `).get(`connector:${connectorId}`).total, 1);

  const commandResponse = await worker.fetch(new Request(
    `https://message.example.com/api/connectors/commands?connectorId=${connectorId}&limit=10`, {
      headers: { authorization: `Bearer ${connectorToken}`, 'x-connector-id': connectorId },
    }), harness.env, harness.ctx);
  assert.equal(commandResponse.status, 200);
  assert.deepEqual((await commandResponse.json()).commands.map((command) => command.id), [fresh.commandId]);
  harness.database.close();
});

test('first enabled registration has no old connector queue to quarantine', async () => {
  const harness = createHarness();
  const response = await register(harness);
  assert.equal(response.status, 201);
  assert.equal(harness.database.prepare(`
    SELECT COUNT(*) AS total FROM audit_log
    WHERE actor = ? AND action = 'connector_send_commands_manual_review'
  `).get(`connector:${connectorId}`).total, 0);
  harness.database.close();
});

test('registration without send_text leaves the old command queue unchanged', async () => {
  const harness = createHarness();
  const { database } = harness;
  const conversationId = seedConnector(database, connectorId, ['receive_text']);
  const pending = seedMessageAndCommand(database, conversationId, connectorId,
    'still-disabled', 'pending');
  const response = await register(harness, ['receive_text']);
  assert.equal(response.status, 201);
  assert.equal(database.prepare('SELECT state FROM commands WHERE id = ?')
    .get(pending.commandId).state, 'pending');
  assert.equal(database.prepare('SELECT delivery_state FROM messages WHERE id = ?')
    .get(pending.messageId).delivery_state, 'queued');
  harness.database.close();
});

test('registration batch rolls back command review if message state update fails', async () => {
  const harness = createHarness();
  const { database } = harness;
  const conversationId = seedConnector(database, connectorId, ['receive_text']);
  const pending = seedMessageAndCommand(database, conversationId, connectorId,
    'rollback', 'pending');
  database.exec(`
    CREATE TRIGGER reject_manual_review BEFORE UPDATE OF delivery_state ON messages
    WHEN NEW.delivery_state = 'manual_review'
    BEGIN SELECT RAISE(ABORT, 'message_review_rejected'); END
  `);

  const response = await register(harness);
  assert.equal(response.status, 400);
  assert.deepEqual(
    JSON.parse(database.prepare('SELECT capabilities_json FROM connector_instances WHERE id = ?')
      .get(connectorId).capabilities_json), ['receive_text'],
  );
  assert.equal(database.prepare('SELECT state FROM commands WHERE id = ?')
    .get(pending.commandId).state, 'pending');
  assert.equal(database.prepare('SELECT delivery_state FROM messages WHERE id = ?')
    .get(pending.messageId).delivery_state, 'queued');
  assert.equal(database.prepare(`
    SELECT COUNT(*) AS total FROM audit_log
    WHERE actor = ? AND action = 'connector_send_commands_manual_review'
  `).get(`connector:${connectorId}`).total, 0);
  harness.database.close();
});
