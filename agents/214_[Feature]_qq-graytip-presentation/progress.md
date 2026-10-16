# Progress

- Created an isolated public worktree from `40e8dba` after checking `git worktree list`.
- Loaded the Cloudflare and Workers best-practices skills, fetched current Workers best-practices and D1 API documentation, and retrieved current `@cloudflare/workers-types` package metadata/types.
- Traced the public message path through bridge spool schema, unified relay, Worker ingest, persisted metadata, inbox API and Vue thread rendering.
- Added explicit `system` marker validation/forwarding from bridge to Worker, constrained to authenticated QQ inbound text events; metadata/body alone cannot create it.
- Added a conditional placeholder update that preserves sender/time/delivery identity and refuses linked attachments, wrong conversations, and real prior text. System rows are not created or exposed as agent prompts.
- Projected only validated inbound QQ system markers to the inbox UI and rendered them centered without member identity/avatar.
- Verified Worker tests (`node --test test/*.test.mjs`: 103/103), bridge check and tests (59/59), UI typecheck/build, synthetic Edge browser navigation/media test, and the spool marker test.
