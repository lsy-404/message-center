import assert from 'node:assert/strict';
import test from 'node:test';
import worker from '../cloudflare-worker/worker/index.js';
import { createOidcFixture } from './helpers/oidc-fixture.mjs';

const origin = 'https://message.example.com';
const humanRoutes = [
  ['GET', '/app'],
  ['GET', '/assets/app.js'],
  ['GET', '/api/inbox'],
  ['GET', '/api/group-text-backups'],
  ['GET', '/api/files/private-file'],
  ['GET', '/api/avatars/device/conversation'],
  ['GET', '/api/sender-avatars/device/sender'],
  ['POST', '/api/files'],
  ['DELETE', '/api/files/private-file'],
  ['POST', '/api/messages/send'],
  ['PUT', '/api/connectors/device/layout-control'],
  ['GET', '/api/conversations/conversation/policy'],
  ['PUT', '/api/conversations/conversation/policy'],
];

test('removing the admin role blocks all human routes before accessing business data', async (t) => {
  for (const [method, path] of humanRoutes) {
    await t.test(`${method} ${path}`, async () => {
      const fixture = await createOidcFixture();
      try {
        const { cookie } = await fixture.authenticated();
        assert.ok(cookie);
        fixture.roles = [];
        const response = await worker.fetch(new Request(`${origin}${path}`, {
          method, headers: { cookie, origin },
        }), fixture.env, {});
        assert.equal(response.status, 403);
        assert.equal((await response.json()).error, 'admin_required');
        assert.equal(fixture.sqlite.prepare('SELECT COUNT(*) AS count FROM oidc_sessions').get().count, 0);
      } finally {
        fixture.restore();
        fixture.sqlite.close();
      }
    });
  }
});

test('human mutations require a same-origin request even with a valid admin session', async () => {
  const fixture = await createOidcFixture();
  try {
    const { cookie } = await fixture.authenticated();
    for (const requestOrigin of [undefined, 'null', 'https://attacker.example']) {
      for (const [method, path] of humanRoutes.filter(([method]) => method !== 'GET')) {
        const response = await worker.fetch(new Request(`${origin}${path}`, {
          method,
          headers: { cookie, ...(requestOrigin === undefined ? {} : { origin: requestOrigin }) },
        }), fixture.env, {});
        assert.equal(response.status, 403);
        assert.equal((await response.json()).error, 'cross_origin_denied');
      }
    }
  } finally {
    fixture.restore();
    fixture.sqlite.close();
  }
});

test('unauthenticated APIs fail closed without requiring provider discovery', async () => {
  const response = await worker.fetch(new Request(`${origin}/api/inbox`), {}, {});
  assert.equal(response.status, 401);
  const download = await worker.fetch(new Request(`${origin}/api/files/private-file`), {}, {});
  assert.equal(download.status, 401);
});
