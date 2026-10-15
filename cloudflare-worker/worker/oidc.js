import {
  authorizationCodeGrant,
  buildAuthorizationUrl,
  calculatePKCECodeChallenge,
  ClientSecretBasic,
  Configuration,
  discovery,
  enableNonRepudiationChecks,
  randomNonce,
  randomPKCECodeVerifier,
  randomState,
  ResponseBodyError,
  refreshTokenGrant,
  tokenIntrospection,
  tokenRevocation,
} from "openid-client";
import { EncryptJWT, createRemoteJWKSet, jwtDecrypt, jwtVerify } from "jose";

const FLOW_COOKIE = "__Host-message_oidc_flow";
const SESSION_COOKIE = "__Host-message_oidc";
const FLOW_SECONDS = 5 * 60;
const SESSION_SECONDS = 12 * 60 * 60;
const REFRESH_LEASE_SECONDS = 20;
const PROVIDER_TIMEOUT_SECONDS = 5;
const METADATA_CACHE_MS = 5 * 60 * 1000;
const encoder = new TextEncoder();
const publicMetadataCache = new Map();

export class OidcAuthError extends Error {
  constructor(code, status = 503) {
    super(code);
    this.name = "OidcAuthError";
    this.code = code;
    this.status = status;
    if (code === "auth_refresh_pending") this.retryAfter = 1;
  }
}

export function clearOidcSessionCookie() {
  return clearCookie(SESSION_COOKIE);
}

function isInvalidGrant(error) {
  return error instanceof ResponseBodyError && error.error === "invalid_grant";
}

function refreshAccessExpiry(tokens) {
  const expiresIn = tokens.expires_in;
  return Math.floor(Date.now() / 1000) + (Number.isFinite(expiresIn) && expiresIn > 0 ? expiresIn : 0);
}

async function persistRotatedTokens(env, cfg, session, owner, updated) {
  const refreshToken = updated.refresh_token === undefined ? session.tokens.refresh_token : updated.refresh_token;
  if (typeof updated.access_token !== "string" || !updated.access_token ||
      typeof refreshToken !== "string" || !refreshToken) return false;
  const envelope = await encryptTokens({
    ...updated,
    refresh_token: refreshToken,
    access_exp: refreshAccessExpiry(updated),
    name: session.tokens.name,
    email: session.tokens.email,
  }, cfg, session.tokens.subject, Date.parse(session.row.expires_at));
  const committed = await env.DB.prepare(`UPDATE oidc_sessions SET token_envelope = ?, refresh_owner = NULL, refresh_until = NULL
    WHERE session_hash = ? AND token_envelope = ? AND refresh_owner = ?`)
    .bind(envelope, session.hash, session.row.token_envelope, owner).run();
  return committed.meta?.changes === 1;
}

function configuration(env) {
  const issuerValue = env.OIDC_ISSUER;
  const clientId = env.OIDC_CLIENT_ID;
  const clientSecret = env.OIDC_CLIENT_SECRET;
  const redirectValue = env.OIDC_REDIRECT_URI;
  const sessionSecret = env.SESSION_SECRET;
  if (![issuerValue, clientId, clientSecret, redirectValue, sessionSecret].every((value) => typeof value === "string" && value.length)) {
    throw new OidcAuthError("auth_unavailable");
  }
  let issuer;
  let redirectUri;
  try {
    issuer = new URL(issuerValue);
    redirectUri = new URL(redirectValue);
  } catch {
    throw new OidcAuthError("auth_unavailable");
  }
  if (issuer.protocol !== "https:" || issuer.username || issuer.password || issuer.hash || issuer.search ||
      redirectUri.protocol !== "https:" || redirectUri.username || redirectUri.password || redirectUri.hash || redirectUri.search ||
      redirectUri.pathname !== "/api/auth/callback" || encoder.encode(sessionSecret).length < 32 || !env.DB) {
    throw new OidcAuthError("auth_unavailable");
  }
  return { issuer, issuerId: issuerValue, clientId, clientSecret, redirectUri, sessionSecret };
}

async function client(env, request) {
  const config = configuration(env);
  let requestUrl;
  try { requestUrl = new URL(request.url); } catch { throw new OidcAuthError("auth_unavailable"); }
  if (requestUrl.origin !== config.redirectUri.origin) throw new OidcAuthError("auth_unavailable");
  let metadata = publicMetadataCache.get(config.issuerId);
  if (metadata && metadata.expiresAt <= Date.now()) {
    publicMetadataCache.delete(config.issuerId);
    metadata = undefined;
  }
  let oidc;
  if (metadata) {
    oidc = new Configuration(metadata.server, config.clientId, config.clientSecret, ClientSecretBasic());
    oidc.timeout = PROVIDER_TIMEOUT_SECONDS;
    enableNonRepudiationChecks(oidc);
  } else {
    oidc = await discovery(config.issuer, config.clientId, config.clientSecret, ClientSecretBasic(), {
      timeout: PROVIDER_TIMEOUT_SECONDS,
      execute: [enableNonRepudiationChecks],
    });
    const server = JSON.parse(JSON.stringify(oidc.serverMetadata()));
    if (server.issuer !== config.issuerId) throw new OidcAuthError("auth_unavailable");
    metadata = { server, expiresAt: Date.now() + METADATA_CACHE_MS };
    publicMetadataCache.set(config.issuerId, metadata);
  }
  if (oidc.serverMetadata().issuer !== config.issuerId ||
      oidc.serverMetadata().id_token_signing_alg_values_supported?.includes("RS256") !== true ||
      !oidc.serverMetadata().introspection_endpoint || !oidc.serverMetadata().token_endpoint) {
    throw new OidcAuthError("auth_unavailable");
  }
  return { ...config, oidc };
}

function cookieValue(request, name) {
  const header = request.headers.get("cookie") || "";
  for (const item of header.split(";")) {
    const separator = item.indexOf("=");
    if (separator > 0 && item.slice(0, separator).trim() === name) return item.slice(separator + 1).trim();
  }
  return "";
}

function setCookie(name, value, maxAge) {
  return `${name}=${value}; Path=/; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=Lax`;
}

function clearCookie(name) {
  return `${name}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax`;
}

function errorResponse(error, headers = {}) {
  const authError = error instanceof OidcAuthError ? error : new OidcAuthError("auth_unavailable");
  return new Response(null, { status: authError.status, headers: { ...headers, "cache-control": "no-store" } });
}

async function seal(value, secret) {
  const key = new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(secret)));
  return new EncryptJWT(value).setProtectedHeader({ alg: "dir", enc: "A256GCM" }).setIssuedAt().setExpirationTime("5m")
    .encrypt(key);
}

async function unseal(value, secret) {
  const key = new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(secret)));
  const { payload } = await jwtDecrypt(value, key, { keyManagementAlgorithms: ["dir"], contentEncryptionAlgorithms: ["A256GCM"] });
  return payload;
}

async function sessionKey(secret) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(secret)));
}

async function encryptTokens(tokens, cfg, subject, expiresAt) {
  const key = await sessionKey(cfg.sessionSecret);
  return new EncryptJWT({ ...tokens, issuer: cfg.issuerId, clientId: cfg.clientId, subject })
    .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
    .setIssuedAt()
    .setExpirationTime(Math.floor(expiresAt / 1000))
    .encrypt(key);
}

async function decryptTokens(envelope, cfg) {
  const key = await sessionKey(cfg.sessionSecret);
  const { payload } = await jwtDecrypt(envelope, key, {
    keyManagementAlgorithms: ["dir"],
    contentEncryptionAlgorithms: ["A256GCM"],
  });
  if (payload.issuer !== cfg.issuerId || payload.clientId !== cfg.clientId || typeof payload.subject !== "string" ||
      typeof payload.access_token !== "string" || typeof payload.refresh_token !== "string" || !Number.isFinite(payload.access_exp)) {
    throw new OidcAuthError("session_invalid", 401);
  }
  return payload;
}

async function introspect(cfg, accessToken) {
  const result = await tokenIntrospection(cfg.oidc, accessToken, { token_type_hint: "access_token" });
  if (result.active !== true || result.client_id !== cfg.clientId || result.token_type?.toLowerCase() !== "bearer" ||
      typeof result.sub !== "string" || !Number.isFinite(result.exp) || result.exp <= Math.floor(Date.now() / 1000) ||
      !Array.isArray(result.roles)) throw new OidcAuthError("admin_required", 403);
  return result;
}

function validateAdminIntrospection(result, cfg, subject) {
  if (result.sub !== subject) throw new OidcAuthError("identity_mismatch", 401);
  if (!result.roles.includes("admin")) throw new OidcAuthError("admin_required", 403);
}

async function revoke(cfg, token, hint) {
  try {
    if (token) await tokenRevocation(cfg.oidc, token, { token_type_hint: hint });
  } catch { /* Revocation failure must not restore local access. */ }
}

export async function beginOidcLogin(request, env) {
  let flowCookie;
  try {
    const cfg = await client(env, request);
    const verifier = randomPKCECodeVerifier();
    const [challenge, state, nonce] = await Promise.all([
      calculatePKCECodeChallenge(verifier),
      Promise.resolve(randomState()),
      Promise.resolve(randomNonce()),
    ]);
    const authorizationUrl = buildAuthorizationUrl(cfg.oidc, {
      redirect_uri: cfg.redirectUri.href,
      scope: "openid profile email offline_access",
      response_type: "code",
      state,
      nonce,
      code_challenge: challenge,
      code_challenge_method: "S256",
    });
    flowCookie = await seal({ state, nonce, verifier }, cfg.sessionSecret);
    return new Response(null, {
      status: 302,
      headers: {
        location: authorizationUrl.href,
        "cache-control": "no-store",
        "set-cookie": setCookie(FLOW_COOKIE, flowCookie, FLOW_SECONDS),
      },
    });
  } catch (error) { return errorResponse(error); }
}

export async function completeOidcLogin(request, env) {
  const clearFlow = { "set-cookie": clearCookie(FLOW_COOKIE) };
  let cfg;
  let tokens;
  try {
    cfg = await client(env, request);
    const callbackUrl = new URL(request.url);
    if (callbackUrl.pathname !== "/api/auth/callback" || callbackUrl.origin !== cfg.redirectUri.origin) {
      throw new OidcAuthError("login_failed", 400);
    }
    const sealedFlow = cookieValue(request, FLOW_COOKIE);
    if (!sealedFlow) throw new OidcAuthError("login_failed", 400);
    const flow = await unseal(sealedFlow, cfg.sessionSecret);
    const state = callbackUrl.searchParams.get("state");
    if (!state || state !== flow.state || callbackUrl.searchParams.has("error")) throw new OidcAuthError("login_failed", 400);
    tokens = await authorizationCodeGrant(cfg.oidc, callbackUrl, {
      pkceCodeVerifier: flow.verifier,
      expectedState: flow.state,
      expectedNonce: flow.nonce,
      idTokenExpected: true,
    });
    if (typeof tokens.id_token !== "string" || typeof tokens.access_token !== "string" || typeof tokens.refresh_token !== "string") {
      throw new OidcAuthError("login_failed", 400);
    }
    const metadata = cfg.oidc.serverMetadata();
    const keySet = createRemoteJWKSet(new URL(metadata.jwks_uri), { timeoutDuration: PROVIDER_TIMEOUT_SECONDS * 1000 });
    const { payload, protectedHeader } = await jwtVerify(tokens.id_token, keySet, {
      issuer: cfg.issuerId,
      audience: cfg.clientId,
      algorithms: ["RS256"],
      clockTolerance: 0,
    });
    if (protectedHeader.alg !== "RS256" || payload.nonce !== flow.nonce || typeof payload.sub !== "string" ||
        !Number.isFinite(payload.exp) || payload.exp <= Math.floor(Date.now() / 1000)) {
      throw new OidcAuthError("login_failed", 400);
    }
    const identity = await introspect(cfg, tokens.access_token);
    if (identity.sub !== payload.sub) throw new OidcAuthError("identity_mismatch", 401);
    validateAdminIntrospection(identity, cfg, payload.sub);
    const expiresAt = Date.now() + SESSION_SECONDS * 1000;
    const opaqueId = base64url(crypto.getRandomValues(new Uint8Array(32)));
    const sessionHash = await hashHex(opaqueId);
    const envelope = await encryptTokens({ ...tokens, access_exp: identity.exp, name: payload.name, email: payload.email }, cfg, payload.sub, expiresAt);
    await env.DB.prepare(`INSERT INTO oidc_sessions (session_hash, subject, token_envelope, expires_at, refresh_owner, refresh_until, created_at)
      VALUES (?, ?, ?, ?, NULL, NULL, ?)`)
      .bind(sessionHash, payload.sub, envelope, new Date(expiresAt).toISOString(), new Date().toISOString()).run();
    const headers = new Headers({ location: "/app", "cache-control": "no-store" });
    headers.append("set-cookie", clearCookie(FLOW_COOKIE));
    headers.append("set-cookie", setCookie(SESSION_COOKIE, opaqueId, SESSION_SECONDS));
    return new Response(null, {
      status: 302,
      headers,
    });
  } catch (error) {
    if (cfg && tokens) {
      await Promise.all([
        revoke(cfg, tokens.refresh_token, "refresh_token"),
        revoke(cfg, tokens.access_token, "access_token"),
      ]);
    }
    const safeError = error instanceof OidcAuthError ? error : new OidcAuthError("login_failed", 400);
    return errorResponse(safeError, clearFlow);
  }
}

async function hashHex(value) {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function base64url(bytes) {
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
}

async function invalidateSession(env, hash, cfg, tokens) {
  const deleted = await env.DB.prepare("DELETE FROM oidc_sessions WHERE session_hash = ? AND token_envelope = ?")
    .bind(hash, tokens.envelope).run();
  if (deleted.meta?.changes !== 1) return;
  await Promise.all([
    revoke(cfg, tokens.refresh_token, "refresh_token"),
    revoke(cfg, tokens.access_token, "access_token"),
  ]);
}

async function refreshSession(env, cfg, session) {
  const owner = crypto.randomUUID();
  const leaseUntil = new Date(Date.now() + REFRESH_LEASE_SECONDS * 1000).toISOString();
  const currentTime = new Date().toISOString();
  const acquired = await env.DB.prepare(`UPDATE oidc_sessions SET refresh_owner = ?, refresh_until = ?
    WHERE session_hash = ? AND token_envelope = ? AND refresh_owner IS NULL`)
    .bind(owner, leaseUntil, session.hash, session.row.token_envelope).run();
  if (acquired.meta?.changes !== 1) {
    const current = await env.DB.prepare("SELECT * FROM oidc_sessions WHERE session_hash = ?").bind(session.hash).first();
    if (current?.token_envelope === session.row.token_envelope && current.refresh_owner && current.refresh_until < currentTime) {
      const error = new OidcAuthError("auth_refresh_failed", 401);
      error.preserveSession = true;
      throw error;
    }
    throw new OidcAuthError("auth_refresh_pending", 503);
  }
  let rotated;
  try {
    const updated = await refreshTokenGrant(cfg.oidc, session.tokens.refresh_token, { scope: "openid profile email offline_access" });
    rotated = updated;
    if (typeof updated.access_token !== "string" || !updated.access_token ||
        (updated.refresh_token !== undefined && (typeof updated.refresh_token !== "string" || !updated.refresh_token))) {
      throw new OidcAuthError("auth_refresh_pending", 503);
    }
    updated.refresh_token ??= session.tokens.refresh_token;
    const identity = await introspect(cfg, updated.access_token);
    validateAdminIntrospection(identity, cfg, session.tokens.subject);
    const envelope = await encryptTokens({ ...updated, access_exp: identity.exp, name: session.tokens.name, email: session.tokens.email }, cfg, session.tokens.subject, Date.parse(session.row.expires_at));
    const committed = await env.DB.prepare(`UPDATE oidc_sessions SET token_envelope = ?, refresh_owner = NULL, refresh_until = NULL
      WHERE session_hash = ? AND token_envelope = ? AND refresh_owner = ?`)
      .bind(envelope, session.hash, session.row.token_envelope, owner).run();
    if (committed.meta?.changes !== 1) throw new OidcAuthError("auth_refresh_pending", 503);
    return {
      ...session,
      row: { ...session.row, token_envelope: envelope },
      tokens: { ...(await decryptTokens(envelope, cfg)), envelope },
    };
  } catch (error) {
    const terminal = (error instanceof OidcAuthError && [401, 403].includes(error.status)) || isInvalidGrant(error);
    if (terminal) {
      const removed = await env.DB.prepare("DELETE FROM oidc_sessions WHERE session_hash = ? AND token_envelope = ? AND refresh_owner = ?")
        .bind(session.hash, session.row.token_envelope, owner).run();
      if (removed.meta?.changes === 1) {
        await Promise.all([
          revoke(cfg, session.tokens.refresh_token, "refresh_token"),
          revoke(cfg, session.tokens.access_token, "access_token"),
          revoke(cfg, rotated?.refresh_token, "refresh_token"),
          revoke(cfg, rotated?.access_token, "access_token"),
        ]);
      }
      throw error instanceof OidcAuthError ? error : new OidcAuthError("auth_refresh_failed", 401);
    }
    if (rotated) {
      const committed = await persistRotatedTokens(env, cfg, session, owner, rotated);
      if (!committed) {
        const current = await env.DB.prepare("SELECT session_hash FROM oidc_sessions WHERE session_hash = ?")
          .bind(session.hash).first();
        if (!current) {
          await Promise.all([
            revoke(cfg, rotated.refresh_token, "refresh_token"),
            revoke(cfg, rotated.access_token, "access_token"),
          ]);
        }
      }
    }
    throw error instanceof OidcAuthError && error.status === 503
      ? error
      : new OidcAuthError("auth_refresh_pending", 503);
  }
}

export async function oidcIdentity(request, env) {
  let cfg;
  let session;
  try {
    const opaqueId = cookieValue(request, SESSION_COOKIE);
    if (!/^[A-Za-z0-9_-]{43}$/u.test(opaqueId)) return null;
    const hash = await hashHex(opaqueId);
    const row = await env.DB.prepare("SELECT * FROM oidc_sessions WHERE session_hash = ? AND expires_at > ?")
      .bind(hash, new Date().toISOString()).first();
    if (!row) return null;
    cfg = configuration(env);
    try {
      const tokens = await decryptTokens(row.token_envelope, cfg);
      if (tokens.subject !== row.subject) throw new OidcAuthError("session_invalid", 401);
      session = { hash, row, tokens: { ...tokens, envelope: row.token_envelope } };
    } catch {
      await env.DB.prepare("DELETE FROM oidc_sessions WHERE session_hash = ? AND token_envelope = ?")
        .bind(hash, row.token_envelope).run();
      return null;
    }
    cfg = await client(env, request);
    if (session.tokens.access_exp <= Math.floor(Date.now() / 1000) + 30) session = await refreshSession(env, cfg, session);
    const identity = await introspect(cfg, session.tokens.access_token);
    validateAdminIntrospection(identity, cfg, session.tokens.subject);
    return { id: `oidc:${identity.sub}`, name: typeof session.tokens.name === "string" ? session.tokens.name : "", email: typeof session.tokens.email === "string" ? session.tokens.email : "", authLabel: "OIDC" };
  } catch (error) {
    if (error instanceof OidcAuthError && [401, 403].includes(error.status)) {
      if (session && !error.preserveSession) {
        await invalidateSession(env, session.hash, cfg, session.tokens);
      }
      if (session) {
        error.clearSessionCookie = true;
      }
      throw error;
    }
    throw error instanceof OidcAuthError ? error : new OidcAuthError("identity_unavailable");
  }
}

export async function logoutOidc(request, env) {
  try {
    const url = new URL(request.url);
    if (request.headers.get("origin") !== url.origin) return new Response(null, { status: 403, headers: { "cache-control": "no-store" } });
    const opaqueId = cookieValue(request, SESSION_COOKIE);
    if (/^[A-Za-z0-9_-]{43}$/u.test(opaqueId) && env?.DB) {
      const hash = await hashHex(opaqueId);
      const row = await env.DB.prepare("DELETE FROM oidc_sessions WHERE session_hash = ? RETURNING *").bind(hash).first();
      if (row) {
        try {
          const cfg = await client(env, request);
          const tokens = await decryptTokens(row.token_envelope, cfg);
          await Promise.all([
            revoke(cfg, tokens.refresh_token, "refresh_token"),
            revoke(cfg, tokens.access_token, "access_token"),
          ]);
        } catch { /* Local deletion is authoritative when the provider is unavailable. */ }
      }
    }
    const headers = new Headers({ location: "/signed-out", "cache-control": "no-store" });
    headers.append("set-cookie", clearCookie(SESSION_COOKIE));
    headers.append("set-cookie", clearCookie(FLOW_COOKIE));
    return new Response(null, { status: 303, headers });
  } catch {
    return new Response(null, { status: 503, headers: { "cache-control": "no-store" } });
  }
}

export async function cleanupOidcSessions(env) {
  if (!env?.DB) throw new OidcAuthError("auth_unavailable");
  const result = await env.DB.prepare("DELETE FROM oidc_sessions WHERE expires_at <= ?").bind(new Date().toISOString()).run();
  return result.meta?.changes || 0;
}
