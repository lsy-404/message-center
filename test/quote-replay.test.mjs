import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

export async function testQuoteReplay({ database, d1, connectorId, stamp, requestEvents, requestBackups, putInboundFile }) {
  const originalKind = database.prepare('SELECT kind FROM connector_instances WHERE id = ?').get(connectorId).kind;
  database.prepare("UPDATE connector_instances SET kind = 'qq' WHERE id = ?").run(connectorId);
  let sequence = 1000;
  const reply = { sourceText: '', sourceTextTruncated: false, sourceExpired: false };
  const seed = (conversationType) => ({
    externalId: `profile-test:qq-message:${sequence++}`,
    conversationExternalId: `quote-replay-${sequence}`,
    conversationTitle: 'Quote replay fixture', senderId: 'member-quote', senderName: 'Member',
    occurredAt: stamp, conversationType, trigger: conversationType === 'group' ? 'background' : 'direct',
    placement: 'normal', body: '[引用消息]\nanswer', contentType: 'text', attachments: [],
  });
  const row = (event) => database.prepare(`
    SELECT id, body, content_type, metadata_json FROM messages WHERE connector_id = ? AND external_id = ?
  `).get(connectorId, event.externalId);
  const post = async (request, event) => {
    const response = await request([event]);
    assert.equal(response.status, 200, JSON.stringify(await response.clone().json()));
    return response.json();
  };
  try {
    for (const kind of ['direct', 'group']) {
      const request = kind === 'group' ? requestBackups : requestEvents;
      const event = seed(kind);
      await post(request, event);
      const originalId = row(event).id;
      const enriched = { ...event, body: 'answer', reply };
      await post(request, enriched);
      await post(request, enriched);
      const stored = row(event);
      assert.equal(stored.id, originalId);
      assert.equal(stored.body, 'answer');
      assert.equal(stored.content_type, 'text');
      assert.deepEqual(JSON.parse(stored.metadata_json).reply, reply);
      assert.equal(database.prepare('SELECT COUNT(*) AS n FROM messages WHERE connector_id = ? AND external_id = ?')
        .get(connectorId, event.externalId).n, 1);
      if (kind === 'group') {
        assert.equal(database.prepare('SELECT body FROM group_text_backups WHERE connector_id = ? AND external_id = ?')
          .get(connectorId, event.externalId).body, 'answer');
      }
      const variants = [
        { body: 'different answer' },
        { senderId: 'different-member' },
        { occurredAt: new Date(Date.parse(stamp) + 1000).toISOString() },
        { conversationExternalId: 'wrong-conversation' },
        { reply: undefined },
      ];
      for (const variant of variants) {
        const protectedEvent = seed(kind);
        await post(request, protectedEvent);
        const response = await request([{ ...protectedEvent, body: 'answer', reply, ...variant }]);
        assert.equal(response.status, 400);
        assert.equal((await response.json()).error, 'message_external_id_conflict');
        assert.equal(row(protectedEvent).body, protectedEvent.body);
      }
    }

    const partial = seed('group');
    await post(requestBackups, partial);
    database.prepare('UPDATE group_text_backups SET body = ? WHERE connector_id = ? AND external_id = ?')
      .run('answer', connectorId, partial.externalId);
    await post(requestBackups, { ...partial, body: 'answer', reply });
    assert.equal(row(partial).body, 'answer');
    assert.deepEqual(JSON.parse(row(partial).metadata_json).reply, reply);

    for (const [column, value] of [['sender_id', 'racing-member'], ['occurred_at', new Date(Date.parse(stamp) + 2000).toISOString()]]) {
      const racing = seed('group');
      await post(requestBackups, racing);
      const originalPrepare = d1.prepare;
      let mutated = false;
      d1.prepare = function (sql) {
        const statement = originalPrepare.call(this, sql);
        if (/UPDATE messages SET body = \?, metadata_json = \?/.test(sql)) {
          const originalBind = statement.bind;
          statement.bind = function (...values) {
            const bound = originalBind.apply(this, values);
            const originalRun = bound.run;
            bound.run = async function () {
              if (!mutated) {
                database.prepare(`UPDATE messages SET ${column} = ? WHERE connector_id = ? AND external_id = ?`)
                  .run(value, connectorId, racing.externalId);
                mutated = true;
              }
              return originalRun.call(this);
            };
            return bound;
          };
        }
        return statement;
      };
      try {
        assert.equal((await requestBackups([{ ...racing, body: 'answer', reply }])).status, 400);
      } finally {
        d1.prepare = originalPrepare;
      }
      assert.equal(mutated, true);
      assert.equal(row(racing).body, racing.body);
      assert.equal(database.prepare(`SELECT ${column} AS value FROM messages WHERE connector_id = ? AND external_id = ?`)
        .get(connectorId, racing.externalId).value, value);
    }

    const image = { ...seed('group'), body: '[引用消息]\n[图片]', contentType: 'mixed' };
    const bytes = new Uint8Array([41, 42, 43, 44]);
    const fileId = 'quote-replay-image';
    assert.equal((await putInboundFile(fileId, fileId, bytes, image.conversationExternalId, 'image/png')).status, 201);
    image.attachments = [{ externalId: fileId, fileName: 'fixture.bin', mimeType: 'image/png',
      sizeBytes: bytes.byteLength, sha256: createHash('sha256').update(bytes).digest('hex') }];
    await post(requestBackups, image);
    const messageId = row(image).id;
    await post(requestBackups, { ...image, body: '[图片]', reply });
    const imageRow = row(image);
    assert.equal(imageRow.id, messageId);
    assert.equal(imageRow.body, '[图片]');
    assert.equal(imageRow.content_type, 'mixed');
    assert.deepEqual(JSON.parse(imageRow.metadata_json).reply, reply);
    assert.equal(database.prepare('SELECT COUNT(*) AS n FROM attachments WHERE message_id = ? AND state = ?')
      .get(messageId, 'received').n, 1);

    const invalidReply = await requestBackups([{ ...seed('group'), reply: { ...reply, sourceExpired: true, sourceText: 'expired content' } }]);
    assert.equal(invalidReply.status, 400);
    assert.equal((await invalidReply.json()).error, 'invalid_reply_preview');

    const nonNative = { ...seed('group'), externalId: 'non-native-quote' };
    await post(requestBackups, nonNative);
    const nonNativeReplay = await requestBackups([{ ...nonNative, body: 'answer', reply }]);
    assert.equal(nonNativeReplay.status, 400);
    assert.equal(row(nonNative).body, nonNative.body);

    const nonQq = seed('group');
    await post(requestBackups, nonQq);
    database.prepare("UPDATE connector_instances SET kind = 'im' WHERE id = ?").run(connectorId);
    assert.equal((await requestBackups([{ ...nonQq, body: 'answer', reply }])).status, 400);
    assert.equal(row(nonQq).body, nonQq.body);
  } finally {
    database.prepare('UPDATE connector_instances SET kind = ? WHERE id = ?').run(originalKind, connectorId);
  }
}
