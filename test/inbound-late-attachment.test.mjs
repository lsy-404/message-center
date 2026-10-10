import assert from 'node:assert/strict';

export async function testLateInboundImageReplay({
  database, connectorId, stamp, createHash, postEvents, putInboundFile, r2Objects,
}) {
  const conversationExternalId = 'conversation-late-image-replay';
  const messageExternalId = 'message-late-image-replay';
  const attachmentExternalId = 'file-late-image-replay';
  const occurredAt = new Date(Date.parse(stamp) + 1000).toISOString();
  const imageBytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const imageSha256 = createHash('sha256').update(imageBytes).digest('hex');
  const placeholderEvent = {
    externalId: messageExternalId, conversationExternalId,
    conversationTitle: 'Late image replay', senderName: 'Member', body: '[图片]',
    contentType: 'text', occurredAt,
    conversationType: 'direct', trigger: 'direct', attachments: [],
  };

  const firstIngest = await postEvents([placeholderEvent]);
  assert.equal(firstIngest.inserted, 1);
  const placeholder = database.prepare(`
    SELECT id, content_type, metadata_json FROM messages
    WHERE connector_id = ? AND external_id = ?
  `).get(connectorId, messageExternalId);
  assert.equal(placeholder.content_type, 'text');
  assert.deepEqual(JSON.parse(placeholder.metadata_json).attachments, []);
  const initialQueueCount = database.prepare(`
    SELECT COUNT(*) AS total FROM agent_queue WHERE message_id = ?
  `).get(placeholder.id).total;
  assert.equal(initialQueueCount, 1);

  const uploaded = await putInboundFile(
    attachmentExternalId, attachmentExternalId, imageBytes,
    conversationExternalId, 'image/png',
  );
  assert.equal(uploaded.status, 201);

  const replay = await postEvents([{
    ...placeholderEvent,
    contentType: 'mixed',
    attachments: [{
      externalId: attachmentExternalId, fileName: 'fixture.bin', mimeType: 'image/png',
      sizeBytes: imageBytes.byteLength, sha256: imageSha256,
    }],
  }]);
  assert.equal(replay.inserted, 0);
  assert.equal(replay.received, 1);

  const enriched = database.prepare(`
    SELECT id, body, content_type, metadata_json FROM messages
    WHERE connector_id = ? AND external_id = ?
  `).get(connectorId, messageExternalId);
  assert.equal(enriched.id, placeholder.id);
  assert.equal(enriched.body, '[图片]');
  assert.equal(enriched.content_type, 'mixed');
  assert.deepEqual(JSON.parse(enriched.metadata_json).attachments, [{
    externalId: attachmentExternalId, fileName: 'fixture.bin', mimeType: 'image/png',
    sizeBytes: imageBytes.byteLength, sha256: imageSha256,
  }]);

  const linked = database.prepare(`
    SELECT message_id, state, object_key FROM attachments WHERE connector_id = ? AND external_id = ?
  `).get(connectorId, attachmentExternalId);
  assert.equal(linked.message_id, placeholder.id);
  assert.equal(linked.state, 'received');
  assert.ok(linked.object_key);
  assert.equal(r2Objects.has(linked.object_key), true);
  assert.equal(database.prepare(`
    SELECT COUNT(*) AS total FROM messages WHERE connector_id = ? AND external_id = ?
  `).get(connectorId, messageExternalId).total, 1);
  assert.equal(database.prepare(`
    SELECT COUNT(*) AS total FROM agent_queue WHERE message_id = ?
  `).get(placeholder.id).total, initialQueueCount);
}
