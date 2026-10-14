# Plan

- [x] Inspect current authentication routes, public/private deployment boundaries and clean remote main.
- [ ] Confirm the existing auth issuer, confidential client registration and authoritative administrator claim.
- [ ] Implement the confidential authorization-code flow with PKCE, state, nonce and strict token validation using a maintained OIDC library.
- [ ] Replace password and administrator bearer authentication with administrator-only OIDC sessions; retain scoped connector and agent machine authentication.
- [ ] Add authorization, callback, session and device-route regressions under root test, plus required build/schema checks.
- [ ] Independently review changes, merge local task commits, verify remote main protection and deliver through the authorized Git path.
- [ ] Configure secrets privately, deploy when the actual client contract is available, and verify live administrator/denial behavior without sending messages or changing device state.
