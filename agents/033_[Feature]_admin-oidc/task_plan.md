# Plan

- [x] Inspect current authentication routes, public/private deployment boundaries and clean remote main.
- [x] Confirm the existing auth issuer and authoritative administrator claim; user confirmed a dedicated client has not yet been created.
- [x] Implement the confidential authorization-code flow with PKCE, state, nonce and strict token validation using a maintained OIDC library.
- [x] Replace password and administrator bearer authentication with administrator-only OIDC sessions; retain scoped connector and agent machine authentication.
- [x] Add authorization, callback, session and device-route regressions under root test, plus required build/schema checks.
- [x] Independently review changes and merge local task commits; remote main is unprotected. Complete the final fast-forward and push after integration validation.
- [x] Configure secrets privately, deploy the registered client, and verify live administrator login, refresh and unauthenticated denial without sending messages or changing device state. Manual logout was confirmed by the user; automated logout remained blocked by the browser.
- [x] Recover registration capability after the user could not locate its credential: verify the credential's narrow purpose, retain the replacement encrypted locally, then register one dedicated client and restrict its provider policy before deployment.
