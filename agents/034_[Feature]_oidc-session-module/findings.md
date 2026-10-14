# Findings

- The worktree starts at the requested base commit and has no local changes.
- `cloudflare-worker/package.json` is absent; a worker-local package manifest and lockfile are required.
- Runtime is Node 24.14.1; `node:sqlite` is available behind Node's experimental flag.
- The session cookie contains 32 cryptographically random bytes encoded as base64url; only its SHA-256 hash is stored in D1.
- The access token is introspected on every authenticated request. Refresh leases never permit an expired owner to reuse a rotating token; an expired lease invalidates the session.
- Provider metadata is public and cached for five minutes; each request gets a new OpenID client Configuration with a five-second timeout.
- The fixture uses generated RSA keys and a realistic discovery, token, JWKS, introspection, and revocation endpoint set.
- Refresh lease acquisition uses an empty-owner compare-and-swap. An expired lease deletes the session; late token results cannot write and are revoked when available.
- Logout uses a single `DELETE ... RETURNING` so a refresh that commits first is revoked from its newest token envelope; a refresh that finishes later cannot recreate the row.
- Preserve the issuer's exact configured string through discovery comparison, ID token verification, metadata cache keys, and encrypted session binding; URL normalization would add a trailing slash and reject valid tokens for issuers without one.
