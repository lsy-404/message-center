import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import test from 'node:test'

test('spool forwards explicit system presentation and rejects unknown presentation values', () => {
  const runner = `
    import assert from 'node:assert/strict';
    import { mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
    import { tmpdir } from 'node:os';
    import { join } from 'node:path';
    import { SpoolBridgeAdapter } from './src/adapters/spool.ts';
    const root = mkdtempSync(join(tmpdir(), 'message-center-spool-presentation-'));
    const runtimeDir = join(root, 'runtime');
    const inbox = join(runtimeDir, 'inbox');
    mkdirSync(inbox, { recursive: true });
    const base = {
      conversation: { id: 'conversation-1', displayName: 'Group', assurance: 'verified' },
      sender: { id: 'sender-1', displayName: 'Member', assurance: 'verified' },
      receivedAt: new Date().toISOString(), text: 'A member joined', attachments: [], replyHandle: 'reply-1',
    };
    writeFileSync(join(inbox, 'accepted.json'), JSON.stringify({ ...base, id: 'accepted', presentation: 'system' }));
    writeFileSync(join(inbox, 'rejected.json'), JSON.stringify({ ...base, id: 'rejected', presentation: 'notice' }));
    const adapter = new SpoolBridgeAdapter({ runtimeDir, stagingDir: join(runtimeDir, 'staging') });
    const received = [];
    try {
      await adapter.start(async (message) => { received.push(message); });
      await adapter.stop();
      assert.equal(received.length, 1);
      assert.equal(received[0].id, 'accepted');
      assert.equal(received[0].presentation, 'system');
      assert.deepEqual(readdirSync(join(runtimeDir, 'processed')), ['accepted.json']);
      assert.equal(readdirSync(join(runtimeDir, 'rejected')).length, 1);
      assert.equal(JSON.parse(readFileSync(join(runtimeDir, 'processed', 'accepted.json'), 'utf8')).presentation, 'system');
    } finally {
      await adapter.stop();
      rmSync(root, { recursive: true, force: true });
    }
  `
  const loader = pathToFileURL(resolve('bridge/node_modules/tsx/dist/loader.mjs')).href
  const result = spawnSync(process.execPath, ['--import', loader, '--input-type=module', '-e', runner], {
    cwd: resolve('bridge'), encoding: 'utf8', timeout: 10_000,
  })
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`)
})
