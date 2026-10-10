# Progress

- Confirmed the configured safe `main` worktree is clean at its current commit and created a separate task branch/worktree.
- Read project instructions and inspected runtime/Worker source and current Python tests; no device, network, deployment, or cloud calls were made.
- Verified both endpoint batch caps (100) and response schemas directly in Worker source. Confirmed the runtime currently sends one outbox row per request and deletes that row after a success predicate that does not validate exact received count.
- Implemented bounded same-route, same-profile text-prefix delivery (20 rows, serialized request capped by existing `MAX_SCAN_RESPONSE`), strict route ACK validation, and atomic exact-row prefix deletion; attachment-bearing events remain single-row.
- Added temporary SQLite adversarial tests for FIFO/profile/route boundaries, byte and message caps, attachment ordering, duplicate ACK counters, partial/malformed/suppressed ACK retention, replay identity, and atomic rollback on a changed selected row.
- Added local Worker integration assertions for two-message first-ingest and duplicate-replay ACKs on both endpoint routes.
- Focused runtime test result: 55 tests passed, 1 platform-specific skip. The Worker integration test passed with two-message first-ingest and replay checks for both routes. Python compilation and `git diff --check` passed.
- Follow-up review closed two failure cases: an over-budget first row now stays queued without a singleton request, and per-connector selection/prefix preparation failures are caught locally so later connectors remain eligible. Added SQLite checks showing malformed and oversized QQ heads do not prevent a valid WeChat delivery, plus a direct no-send retention check for an oversized head. Updated runtime suite result: 58 tests passed, 1 platform-specific skip; Worker integration and `git diff --check` passed.
- No live device, deployment, production cloud request, or push was performed.
