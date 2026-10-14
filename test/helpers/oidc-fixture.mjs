import { DatabaseSync } from "node:sqlite";
import { createRequire } from "node:module";
import { beginOidcLogin, completeOidcLogin } from "../../cloudflare-worker/worker/oidc.js";

const require = createRequire(new URL("../../cloudflare-worker/package.json", import.meta.url));
const { calculatePKCECodeChallenge } = require("openid-client");
const { exportJWK, generateKeyPair, SignJWT } = require("jose");

const ISSUER = "https://issuer.example.com";
const ENDPOINT_ROOT = `${ISSUER}/`;
const REDIRECT_URI = "https://message.example.com/api/auth/callback";
const APP_URL = "https://message.example.com";
const CLIENT_ID = "message-center-test";
const CLIENT_SECRET = "test-client-secret";
const SESSION_SECRET = "test-session-secret-with-at-least-32-bytes";

function responseJson(value, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}

function d1Database() {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(`CREATE TABLE oidc_sessions (
    session_hash TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    token_envelope TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    refresh_owner TEXT,
    refresh_until TEXT,
    created_at TEXT NOT NULL
  )`);
  return {
    sqlite,
    DB: {
      prepare(sql) {
        let values = [];
        const prepared = {
          bind(...bound) { values = bound; return prepared; },
          first() { return sqlite.prepare(sql).get(...values) ?? null; },
          all() { return { results: sqlite.prepare(sql).all(...values) }; },
          run() {
            const result = sqlite.prepare(sql).run(...values);
            return { success: true, meta: { changes: Number(result.changes) } };
          },
        };
        return prepared;
      },
    },
  };
}

export async function createOidcFixture(options = {}) {
  const { publicKey, privateKey } = await generateKeyPair("RS256", { modulusLength: 2048 });
  const jwk = await exportJWK(publicKey);
  jwk.kid = "fixture-key";
  jwk.alg = "RS256";
  jwk.use = "sig";
  const sql = d1Database();
  const baseEnv = {
    OIDC_ISSUER: options.configIssuer ?? ISSUER,
    OIDC_CLIENT_ID: CLIENT_ID,
    OIDC_CLIENT_SECRET: CLIENT_SECRET,
    OIDC_REDIRECT_URI: REDIRECT_URI,
    SESSION_SECRET,
    DB: sql.DB,
  };
  const fixture = {
    roles: options.roles ?? ["admin"],
    subject: options.subject ?? "subject-123",
    introspectionSubject: options.introspectionSubject,
    tokenExpiry: options.tokenExpiry,
    claims: options.loginClaims ?? {},
    refreshCalls: 0,
    authorizationUsed: false,
    introspectionCalls: 0,
    introspectedTokens: [],
    revocations: [],
    authorizationHeaders: [],
    bodyContainsClientSecret: false,
    tokenRequestHook: null,
    async authenticated() {
      const { response } = await this.login();
      const cookieHeaders = response.headers.getSetCookie();
      const sessionCookie = cookieHeaders.map((value) => value.split(";", 1)[0]).find((value) => value.startsWith("__Host-message_oidc="));
      return sessionCookie ? { cookie: sessionCookie, response } : { cookie: "", response };
    },
    async signIdentity(nonce, overrides = {}) {
      return new SignJWT({ nonce: overrides.nonce ?? nonce, name: "Test Admin", email: "admin@example.com" })
        .setProtectedHeader({ alg: overrides.alg ?? "RS256", kid: jwk.kid })
        .setIssuer(overrides.issuer ?? ISSUER)
        .setAudience(overrides.audience ?? CLIENT_ID)
        .setSubject(overrides.subject ?? this.subject)
        .setIssuedAt()
        .setExpirationTime(overrides.expiration ?? "5m")
        .sign(overrides.privateKey ?? privateKey);
    },
    env: baseEnv,
    sqlite: sql.sqlite,
  };

  const originalFetch = globalThis.fetch;
  const fetchMock = async (input, init = {}) => {
    const url = new URL(typeof input === "string" || input instanceof URL ? input : input.url);
    if ([`${ENDPOINT_ROOT}token`, `${ENDPOINT_ROOT}introspect`, `${ENDPOINT_ROOT}revoke`].includes(url.href)) {
      fixture.authorizationHeaders.push(new Headers(init.headers).get("authorization"));
      fixture.bodyContainsClientSecret ||= new URLSearchParams(init.body).has("client_secret");
    }
    if (url.href === `${ENDPOINT_ROOT}.well-known/openid-configuration`) {
      return responseJson({
        issuer: ISSUER,
        authorization_endpoint: `${ENDPOINT_ROOT}authorize`,
        token_endpoint: `${ENDPOINT_ROOT}token`,
        introspection_endpoint: `${ENDPOINT_ROOT}introspect`,
        revocation_endpoint: `${ENDPOINT_ROOT}revoke`,
        jwks_uri: `${ENDPOINT_ROOT}jwks`,
        code_challenge_methods_supported: ["S256"],
        grant_types_supported: ["authorization_code", "refresh_token"],
        response_types_supported: ["code"],
        subject_types_supported: ["public"],
        id_token_signing_alg_values_supported: ["RS256"],
        token_endpoint_auth_methods_supported: ["client_secret_basic"],
      });
    }
    if (url.href === `${ENDPOINT_ROOT}jwks`) return responseJson({ keys: [jwk] });
    if (url.href === `${ENDPOINT_ROOT}token`) {
      const form = new URLSearchParams(init.body);
      if (fixture.tokenRequestHook) await fixture.tokenRequestHook(form);
      if (form.get("grant_type") === "authorization_code") {
        const expected = locationForLogin?.searchParams.get("code_challenge");
        if (fixture.authorizationUsed || !expected || await calculatePKCECodeChallenge(form.get("code_verifier")) !== expected || form.get("redirect_uri") !== REDIRECT_URI) {
          return responseJson({ error: "invalid_grant" }, 400);
        }
        fixture.authorizationUsed = true;
        const idToken = await fixture.signIdentity(locationForLogin.searchParams.get("nonce"), fixture.claims);
        return responseJson({ access_token: "access-initial", refresh_token: "refresh-initial", id_token: idToken, token_type: "Bearer", expires_in: 300 });
      }
      if (form.get("grant_type") === "refresh_token") {
        fixture.refreshCalls += 1;
        return responseJson({ access_token: `access-refreshed-${fixture.refreshCalls}`, refresh_token: `refresh-rotated-${fixture.refreshCalls}`, token_type: "Bearer", expires_in: 300 });
      }
      return responseJson({ error: "unsupported_grant_type" }, 400);
    }
    if (url.href === `${ENDPOINT_ROOT}introspect`) {
      fixture.introspectionCalls += 1;
      const form = new URLSearchParams(init.body);
      const token = form.get("token");
      fixture.introspectedTokens.push(token);
      const expired = options.inactiveTokens?.includes(token) ?? false;
      return responseJson({
        active: !expired,
        client_id: options.introspectionClientId ?? CLIENT_ID,
        sub: fixture.introspectionSubject ?? fixture.subject,
        exp: token?.startsWith("access-refreshed-") ? Math.floor(Date.now() / 1000) + 300 : fixture.tokenExpiry ?? Math.floor(Date.now() / 1000) + 300,
        iat: Math.floor(Date.now() / 1000) - 5,
        token_type: options.tokenType ?? "Bearer",
        roles: fixture.roles,
      });
    }
    if (url.href === `${ENDPOINT_ROOT}revoke`) {
      fixture.revocations.push(new URLSearchParams(init.body).get("token"));
      return new Response(null, { status: 200 });
    }
    return originalFetch(input, init);
  };
  globalThis.fetch = fetchMock;
  let locationForLogin;
  const env = { ...baseEnv };
  fixture.env = env;
  fixture.sqlite = sql.sqlite;
  fixture.login = async (overrides = {}) => {
    const begin = await beginOidcLogin(new Request(`${APP_URL}/login`), env);
    locationForLogin = new URL(begin.headers.get("location"));
    const flowCookie = begin.headers.get("set-cookie").split(";", 1)[0];
    let callbackUrl = `${REDIRECT_URI}?code=fixture-code&state=${encodeURIComponent(overrides.state ?? locationForLogin.searchParams.get("state"))}`;
    if (overrides.error) callbackUrl += `&error=${encodeURIComponent(overrides.error)}`;
    const response = await completeOidcLogin(new Request(callbackUrl, { headers: { cookie: overrides.flowCookie ?? flowCookie } }), env);
    return { response, location: locationForLogin, flowCookie, callbackUrl };
  };
  fixture.restore = () => { globalThis.fetch = originalFetch; };
  return fixture;
}

export async function createAdminTestAuth(businessEnv = {}) {
  const fixture = await createOidcFixture();
  const businessDb = businessEnv.DB;
  fixture.env.DB = Object.assign(Object.create(businessDb || null), {
    prepare(sqlText) {
      if (/\boidc_sessions\b/i.test(sqlText)) return fixture.sqlite ? fixture.env.DB.__oidc.prepare(sqlText) : businessDb.prepare(sqlText);
      return businessDb.prepare(sqlText);
    },
  });
  fixture.env.DB.__oidc = {
    prepare(sqlText) {
      const prepared = fixture.sqlite.prepare(sqlText);
      let values = [];
      const wrapped = {
        bind(...args) { values = args; return wrapped; },
        first() { return prepared.get(...values) ?? null; },
        all() { return { results: prepared.all(...values) }; },
        run() { const result = prepared.run(...values); return { success: true, meta: { changes: Number(result.changes) } }; },
      };
      return wrapped;
    },
  };
  const { response } = await fixture.login();
  if (response.status !== 302) throw new Error(`OIDC fixture login failed with status ${response.status}`);
  const cookie = response.headers.getSetCookie().map((value) => value.split(";", 1)[0]).find((value) => value.startsWith("__Host-message_oidc="));
  const headers = { cookie, origin: APP_URL };
  return { env: { ...businessEnv, ...fixture.env }, headers, restore() { fixture.restore(); fixture.sqlite.close(); } };
}
