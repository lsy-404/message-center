# OIDC refresh recovery

## Goal
Restore reliable administrator OIDC sessions after access-token expiry while preserving confidential client authorization and independent machine credentials.

## Constraints
- No Cloudflare deployment or live state mutation.
- No legacy bearer/password bypass or private provider/credential data in public files.
- Transient provider failures must not destroy local sessions; terminal invalid sessions must clear browser state and guide HTML navigation back through login while API callers receive JSON errors.
- All new tests stay in root `/test`.

## Plan
- [x] Inspect OIDC refresh/session logic, Worker request routing, browser auth handling, and `openid-client` error contracts.
- [x] Implement standards-compliant optional refresh-token rotation and classify terminal versus transient failures without unsafe token reuse after ambiguous rotation.
- [x] Clear stale browser cookies and redirect HTML requests to reauthentication while retaining JSON API error responses.
- [x] Add focused regression tests for optional rotation, provider 5xx/network errors, invalid grants, and HTML/API handling.
- [x] Run focused tests and relevant static checks, review diff, and commit locally.
