# Progress

- Created an isolated public worktree from `40e8dba` after checking `git worktree list`.
- Loaded the Cloudflare and Workers best-practices skills, fetched current Workers best-practices and D1 API documentation, and retrieved current `@cloudflare/workers-types` package metadata/types.
- Traced the public message path through bridge spool schema, unified relay, Worker ingest, persisted metadata, inbox API and Vue thread rendering.
- Added explicit `system` marker validation/forwarding from bridge to Worker, constrained to authenticated QQ inbound text events; metadata/body alone cannot create it.
- Added a conditional placeholder update that preserves sender/time/delivery identity and refuses linked attachments, wrong conversations, and real prior text. System rows are not created or exposed as agent prompts.
- Projected only validated inbound QQ system markers to the inbox UI and rendered them centered without member identity/avatar.
- Verified Worker tests (`node --test test/*.test.mjs`: 103/103), bridge check and tests (59/59), UI typecheck/build, synthetic Edge browser navigation/media test, and the spool marker test.
- Closed the historical-placeholder metadata race with an exact `metadata_json` compare-and-swap; added metadata-only attachment interleaving coverage.
- Prevented replies to upgraded system rows both at authorization and at the atomic outbound insert, including an already-leased row and an upgrade-between-read-and-insert fixture.
- Routed validated QQ system events through the normal Python device-runtime event endpoint and rejected malformed markers before routing. Rechecked malformed inbox metadata does not project a system marker.
- Final verification: Worker 103/103 serial, Python device runtime 108 tests (2 skipped), bridge typecheck and 59 tests pass.
