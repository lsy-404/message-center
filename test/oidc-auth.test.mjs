import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { beginOidcLogin, cleanupOidcSessions, completeOidcLogin, logoutOidc, oidcIdentity } from "../cloudflare-worker/worker/oidc.js";
import { createOidcFixture, createAdminTestAuth } from "./helpers/oidc-fixture.mjs";

const require = createRequire(new URL("../cloudflare-worker/package.json", import.meta.url));
const { generateKeyPair } = require("jose");

async function withFixture(options, run) {
  const fixture = await createOidcFixture(options);
  try { await run(fixture); } finally { fixture.restore(); fixture.sqlite.close(); }
}

function identityRequest(cookie) {
  return new Request("https://message.example.com/api/inbox", { headers: { cookie } });
}

test("login uses state, nonce, PKCE S256 and creates an opaque encrypted admin session", async () => {
  await withFixture({}, async (fixture) => {
    const { response, location } = await fixture.login();
    assert.equal(response.status, 302);
    assert.equal(response.headers.get("location"), "/app");
    assert.equal(location.searchParams.get("scope"), "openid profile email offline_access");
    assert.equal(location.searchParams.get("code_challenge_method"), "S256");
    assert.ok(location.searchParams.get("state"));
    assert.ok(location.searchParams.get("nonce"));
    assert.equal(response.headers.getSetCookie().length, 2);
    const sessionCookie = response.headers.getSetCookie().find((value) => value.startsWith("__Host-message_oidc="));
    assert.match(sessionCookie, /HttpOnly; Secure; SameSite=Lax/);
    assert.doesNotMatch(sessionCookie, /access-initial|refresh-initial/);
    const rows = fixture.sqlite.prepare("SELECT * FROM oidc_sessions").all();
    assert.equal(rows.length, 1);
    assert.doesNotMatch(rows[0].token_envelope, /access-initial|refresh-initial/);
    const cookie = sessionCookie.split(";", 1)[0];
    assert.deepEqual(await oidcIdentity(identityRequest(cookie), fixture.env), {
      id: "oidc:subject-123", name: "Test Admin", email: "admin@example.com", authLabel: "OIDC",
    });
  });
});

test("ordinary users and mismatched introspected subjects cannot log in", async (t) => {
  await t.test("ordinary user", async () => withFixture({ roles: [] }, async (fixture) => {
    const { response } = await fixture.login();
    assert.equal(response.status, 403);
    assert.equal(fixture.sqlite.prepare("SELECT count(*) AS count FROM oidc_sessions").get().count, 0);
    assert.doesNotMatch(response.headers.get("set-cookie"), /access-initial|refresh-initial/);
    assert.deepEqual(new Set(fixture.revocations), new Set(["access-initial", "refresh-initial"]));
  }));
  await t.test("subject mismatch", async () => withFixture({ introspectionSubject: "someone-else" }, async (fixture) => {
    const { response } = await fixture.login();
    assert.equal(response.status, 401);
    assert.equal(fixture.sqlite.prepare("SELECT count(*) AS count FROM oidc_sessions").get().count, 0);
  }));
});

test("callback rejects state, nonce, issuer, audience, expiration, and signature failures", async (t) => {
  await t.test("state mismatch", async () => withFixture({}, async (fixture) => {
    const { response } = await fixture.login({ state: "attacker-state" });
    assert.equal(response.status, 400);
    assert.match(response.headers.get("set-cookie"), /Max-Age=0/);
  }));
  for (const [label, claims] of [
    ["nonce", { nonce: "wrong-nonce" }],
    ["issuer", { issuer: "https://wrong.example.com/" }],
    ["audience", { audience: "another-client" }],
    ["expiration", { expiration: Math.floor(Date.now() / 1000) - 1 }],
  ]) {
    await t.test(label, async () => withFixture({ loginClaims: claims }, async (fixture) => {
      const { response } = await fixture.login();
      assert.equal(response.status, 400);
      assert.equal(fixture.sqlite.prepare("SELECT count(*) AS count FROM oidc_sessions").get().count, 0);
    }));
  }
  await t.test("signature", async () => withFixture({}, async (fixture) => {
    const { privateKey: wrongPrivateKey } = await generateKeyPair("RS256", { modulusLength: 2048 });
    fixture.claims = { privateKey: wrongPrivateKey };
    const { response } = await fixture.login();
    assert.equal(response.status, 400);
    assert.equal(fixture.sqlite.prepare("SELECT count(*) AS count FROM oidc_sessions").get().count, 0);
  }));
});

test("an authorization code callback cannot be replayed", async () => {
  await withFixture({}, async (fixture) => {
    const { response, callbackUrl, flowCookie } = await fixture.login();
    assert.equal(response.status, 302);
    const replay = await completeOidcLogin(new Request(callbackUrl, { headers: { cookie: flowCookie } }), fixture.env);
    assert.equal(replay.status, 400);
    assert.equal(fixture.sqlite.prepare("SELECT count(*) AS count FROM oidc_sessions").get().count, 1);
  });
});

test("issuer string must exactly match discovery metadata including trailing slash", async () => {
  await withFixture({ configIssuer: "https://issuer.example.com/" }, async (fixture) => {
    const response = await beginOidcLogin(new Request("https://message.example.com/login"), fixture.env);
    assert.equal(response.status, 503);
    assert.equal(response.headers.has("location"), false);
  });
});

test("legacy session cookie is ignored and introspection is live for each identity", async () => {
  await withFixture({}, async (fixture) => {
    assert.equal(await oidcIdentity(identityRequest("__Host-message_session=legacy-value"), fixture.env), null);
    const emptyDb = { prepare() { return { bind() { return this; }, first() { return null; } }; } };
    assert.equal(await oidcIdentity(identityRequest(""), { DB: emptyDb }), null);
    const { cookie } = await fixture.authenticated();
    fixture.roles = [];
    await assert.rejects(oidcIdentity(identityRequest(cookie), fixture.env), (error) => error.code === "admin_required" && error.status === 403);
    assert.ok(fixture.introspectionCalls >= 2);
  });
});

test("provider token operations use HTTP Basic and never put the client secret in the form", async () => {
  await withFixture({}, async (fixture) => {
    const { cookie } = await fixture.authenticated();
    await oidcIdentity(identityRequest(cookie), fixture.env);
    assert.ok(fixture.authorizationHeaders.length >= 3);
    for (const header of fixture.authorizationHeaders) {
      assert.match(header, /^Basic /);
      assert.equal(atob(header.slice(6)), "message%2Dcenter%2Dtest:test%2Dclient%2Dsecret");
    }
    assert.equal(fixture.bodyContainsClientSecret, false);
  });
});

test("refresh is leased, rotates once, and rejects concurrent requests without reusing the token", async () => {
  await withFixture({ tokenExpiry: Math.floor(Date.now() / 1000) + 10 }, async (fixture) => {
    const { cookie } = await fixture.authenticated();
    let entered;
    const enteredPromise = new Promise((resolve) => { entered = resolve; });
    let release;
    const releasePromise = new Promise((resolve) => { release = resolve; });
    fixture.tokenRequestHook = async (form) => {
      if (form.get("grant_type") === "refresh_token") {
        entered();
        await releasePromise;
      }
    };
    const first = oidcIdentity(identityRequest(cookie), fixture.env);
    await enteredPromise;
    await assert.rejects(oidcIdentity(identityRequest(cookie), fixture.env), (error) => error.code === "auth_refresh_pending" && error.status === 503);
    release();
    assert.equal((await first).id, "oidc:subject-123");
    assert.equal(fixture.refreshCalls, 1);
    assert.ok(fixture.introspectedTokens.includes("access-refreshed-1"));
  });
});

test("an expired refresh lease quarantines the session while the late owner can finish", async () => {
  await withFixture({ tokenExpiry: Math.floor(Date.now() / 1000) + 10 }, async (fixture) => {
    const { cookie } = await fixture.authenticated();
    let arrivalCount = 0;
    let release;
    const arrivals = new Promise((resolve) => { release = resolve; });
    fixture.tokenRequestHook = async (form) => {
      if (form.get("grant_type") !== "refresh_token") return;
      arrivalCount += 1;
      if (arrivalCount === 1) await arrivals;
    };
    const oldOwner = oidcIdentity(identityRequest(cookie), fixture.env);
    while (arrivalCount < 1) await new Promise((resolve) => setTimeout(resolve, 0));
    fixture.sqlite.prepare("UPDATE oidc_sessions SET refresh_until = ?").run("2000-01-01T00:00:00.000Z");
    await assert.rejects(oidcIdentity(identityRequest(cookie), fixture.env), (error) => error.code === "auth_refresh_failed" && error.clearSessionCookie === true);
    assert.equal(fixture.sqlite.prepare("SELECT count(*) AS count FROM oidc_sessions").get().count, 1);
    release();
    assert.equal((await oldOwner).id, "oidc:subject-123");
    const row = fixture.sqlite.prepare("SELECT * FROM oidc_sessions").get();
    assert.ok(row.token_envelope);
    assert.equal(row.refresh_owner, null);
    assert.equal(fixture.revocations.length, 0);
  });
});

test("logout racing a refresh removes the row and the late rotated token", async () => {
  await withFixture({ tokenExpiry: Math.floor(Date.now() / 1000) + 10 }, async (fixture) => {
    const { cookie } = await fixture.authenticated();
    let release;
    const blocked = new Promise((resolve) => { release = resolve; });
    let entered;
    const enteredPromise = new Promise((resolve) => { entered = resolve; });
    fixture.tokenRequestHook = async (form) => {
      if (form.get("grant_type") === "refresh_token") {
        entered();
        await blocked;
      }
    };
    const refresh = oidcIdentity(identityRequest(cookie), fixture.env);
    await enteredPromise;
    const logout = await logoutOidc(new Request("https://message.example.com/api/auth/logout", {
      method: "POST", headers: { cookie, origin: "https://message.example.com" },
    }), fixture.env);
    assert.equal(logout.status, 303);
    release();
    await assert.rejects(refresh, (error) => error.code === "auth_refresh_pending");
    assert.equal(fixture.sqlite.prepare("SELECT count(*) AS count FROM oidc_sessions").get().count, 0);
    assert.ok(fixture.revocations.includes("refresh-initial"));
    assert.ok(fixture.revocations.includes("refresh-rotated-1"));
  });
});

test("refresh responses may omit or reuse the refresh token", async (t) => {
  for (const mode of ["omit", "same"]) {
    await t.test(mode, async () => withFixture({ tokenExpiry: Math.floor(Date.now() / 1000) + 10, refreshTokenMode: mode }, async (fixture) => {
      const { cookie } = await fixture.authenticated();
      assert.equal((await oidcIdentity(identityRequest(cookie), fixture.env)).id, "oidc:subject-123");
      const row = fixture.sqlite.prepare("SELECT * FROM oidc_sessions").get();
      assert.equal(row.refresh_owner, null);
      assert.equal(fixture.refreshCalls, 1);
      assert.equal(fixture.revocations.length, 0);
      assert.equal((await oidcIdentity(identityRequest(cookie), fixture.env)).id, "oidc:subject-123");
      assert.equal(fixture.refreshCalls, 1);
    }));
  }
});

test("ambiguous provider errors retain the session lease and do not retry the old token", async (t) => {
  for (const failure of ["server_error", "network"]) {
    await t.test(failure, async () => withFixture({ tokenExpiry: Math.floor(Date.now() / 1000) + 10 }, async (fixture) => {
      const { cookie } = await fixture.authenticated();
      fixture.refreshFailure = failure;
      await assert.rejects(oidcIdentity(identityRequest(cookie), fixture.env), (error) => error.code === "auth_refresh_pending" && error.status === 503);
      const row = fixture.sqlite.prepare("SELECT * FROM oidc_sessions").get();
      assert.ok(row);
      assert.ok(row.refresh_owner);
      assert.equal(fixture.revocations.length, 0);
      await assert.rejects(oidcIdentity(identityRequest(cookie), fixture.env), (error) => error.code === "auth_refresh_pending" && error.status === 503);
      assert.equal(fixture.refreshCalls, 1);
      fixture.sqlite.prepare("UPDATE oidc_sessions SET refresh_until = ?").run("2000-01-01T00:00:00.000Z");
      await assert.rejects(oidcIdentity(identityRequest(cookie), fixture.env), (error) => error.code === "auth_refresh_failed" && error.clearSessionCookie === true);
      assert.equal(fixture.sqlite.prepare("SELECT count(*) AS count FROM oidc_sessions").get().count, 1);
      assert.equal(fixture.revocations.length, 0);
    }));
  }
});

test("a rotated refresh token is saved when introspection is temporarily unavailable", async () => {
  await withFixture({ tokenExpiry: Math.floor(Date.now() / 1000) + 10 }, async (fixture) => {
    const { cookie } = await fixture.authenticated();
    fixture.introspectionFailure = true;
    await assert.rejects(oidcIdentity(identityRequest(cookie), fixture.env), (error) => error.code === "auth_refresh_pending" && error.status === 503);
    const row = fixture.sqlite.prepare("SELECT * FROM oidc_sessions").get();
    assert.ok(row);
    assert.equal(row.refresh_owner, null);
    assert.equal(fixture.revocations.length, 0);
    fixture.introspectionFailure = false;
    assert.equal((await oidcIdentity(identityRequest(cookie), fixture.env)).id, "oidc:subject-123");
    assert.equal(fixture.refreshCalls, 1);
    assert.ok(fixture.introspectedTokens.includes("access-refreshed-1"));
  });
});

test("an explicit invalid_grant is terminal and removes the session", async () => {
  await withFixture({ tokenExpiry: Math.floor(Date.now() / 1000) + 10 }, async (fixture) => {
    const { cookie } = await fixture.authenticated();
    fixture.refreshFailure = "invalid_grant";
    await assert.rejects(oidcIdentity(identityRequest(cookie), fixture.env), (error) => error.code === "auth_refresh_failed" && error.status === 401);
    assert.equal(fixture.sqlite.prepare("SELECT count(*) AS count FROM oidc_sessions").get().count, 0);
    assert.ok(fixture.revocations.includes("refresh-initial"));
  });
});

test("logout requires same-origin, removes the row, revokes tokens, and clears cookie", async () => {
  await withFixture({}, async (fixture) => {
    const { cookie } = await fixture.authenticated();
    const crossOrigin = await logoutOidc(new Request("https://message.example.com/api/auth/logout", {
      method: "POST", headers: { cookie, origin: "https://attacker.example" },
    }), fixture.env);
    assert.equal(crossOrigin.status, 403);
    assert.equal(crossOrigin.headers.has("set-cookie"), false);
    assert.equal(fixture.sqlite.prepare("SELECT count(*) AS count FROM oidc_sessions").get().count, 1);
    const response = await logoutOidc(new Request("https://message.example.com/api/auth/logout", {
      method: "POST", headers: { cookie, origin: "https://message.example.com" },
    }), fixture.env);
    assert.equal(response.status, 303);
    assert.equal(response.headers.get("location"), "/signed-out");
    assert.match(response.headers.get("set-cookie"), /Max-Age=0/);
    assert.equal(fixture.sqlite.prepare("SELECT count(*) AS count FROM oidc_sessions").get().count, 0);
    assert.deepEqual(new Set(fixture.revocations), new Set(["access-initial", "refresh-initial"]));
  });
});

test("logout deletes the local session even when provider revocation is unavailable", async () => {
  await withFixture({}, async (fixture) => {
    const { cookie } = await fixture.authenticated();
    const providerFetch = globalThis.fetch;
    globalThis.fetch = async () => { throw new Error("provider unavailable"); };
    try {
      const response = await logoutOidc(new Request("https://message.example.com/api/auth/logout", {
        method: "POST", headers: { cookie, origin: "https://message.example.com" },
      }), fixture.env);
      assert.equal(response.status, 303);
      assert.equal(fixture.sqlite.prepare("SELECT count(*) AS count FROM oidc_sessions").get().count, 0);
    } finally { globalThis.fetch = providerFetch; }
  });
});

test("expired sessions are cleaned and root tests receive a real OIDC cookie with delegated business DB", async () => {
  await withFixture({}, async (fixture) => {
    fixture.sqlite.prepare("INSERT INTO oidc_sessions VALUES (?, ?, ?, ?, NULL, NULL, ?)")
      .run("expired", "subject", "opaque", "2000-01-01T00:00:00.000Z", "2000-01-01T00:00:00.000Z");
    assert.equal(await cleanupOidcSessions(fixture.env), 1);
  });
  const originalFetch = globalThis.fetch;
  const businessEnv = { DB: { prepare: () => { throw new Error("business DB should not be queried during fixture login"); } }, FLAG: "business" };
  const auth = await createAdminTestAuth(businessEnv);
  try {
    assert.equal(auth.env.FLAG, "business");
    assert.match(auth.headers.cookie, /^__Host-message_oidc=/);
    assert.deepEqual(await oidcIdentity(new Request("https://message.example.com/", { headers: auth.headers }), auth.env), {
      id: "oidc:subject-123", name: "Test Admin", email: "admin@example.com", authLabel: "OIDC",
    });
  } finally { auth.restore(); globalThis.fetch = originalFetch; }
});
