import test from "node:test";
import assert from "node:assert/strict";
import worker from "../cloudflare-worker/worker/index.js";
import { createOidcFixture } from "./helpers/oidc-fixture.mjs";

async function terminalFixture() {
  const fixture = await createOidcFixture({ tokenExpiry: Math.floor(Date.now() / 1000) + 10 });
  const { cookie } = await fixture.authenticated();
  fixture.refreshFailure = "invalid_grant";
  return { fixture, cookie };
}

test("terminal browser navigation clears the session cookie and redirects to login", async () => {
  const { fixture, cookie } = await terminalFixture();
  try {
    const response = await worker.fetch(new Request("https://message.example.com/", {
      headers: { cookie, accept: "text/html,application/xhtml+xml" },
    }), fixture.env, {});
    assert.equal(response.status, 303);
    assert.equal(response.headers.get("location"), "/login");
    assert.match(response.headers.get("set-cookie"), /__Host-message_oidc=; Path=\/; Max-Age=0/);
    assert.equal(await response.text(), "");
  } finally { fixture.restore(); fixture.sqlite.close(); }
});

test("terminal API auth failure stays JSON and clears the session cookie", async () => {
  const { fixture, cookie } = await terminalFixture();
  try {
    const response = await worker.fetch(new Request("https://message.example.com/api/inbox", {
      headers: { cookie, accept: "application/json" },
    }), fixture.env, {});
    assert.equal(response.status, 401);
    assert.deepEqual(await response.json(), { ok: false, error: "auth_refresh_failed" });
    assert.match(response.headers.get("set-cookie"), /__Host-message_oidc=; Path=\/; Max-Age=0/);
  } finally { fixture.restore(); fixture.sqlite.close(); }
});
