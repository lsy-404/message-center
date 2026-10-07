# Progress

- Read agent-mode workflow and project rules.
- Inspected `bridge/src/unified-relay.ts`, `bridge/src/adapters/device.ts`, `cloudflare-worker/CONNECTOR_PROTOCOL.md`, Worker event and command handlers, and existing cursor/idempotency tests.
- Added standard-library Python runtime and private adapter contract with one relay process for multiple connector identities.
- Added bounded transactional SQLite outbox/cursors, direct HTTPS requests with redirects disabled, per-connector heartbeat and scan pacing, serialized command polling, lease renewal, and fail-closed idempotency ledger.
- Added an optional launchd example without installing or enabling a service.
- Initial implementation was committed as `0d5c3d9` on `feature/device-runtime`.
- Review fixes: removed duplicate test methods and attachment check; bounded adapter stdin/stdout/wait with a single monotonic deadline and process-group cleanup; added per-connector network backoff; resolved local paths from the config directory and set private umask before SQLite/lock creation; strengthened Worker payload, cursor, and external-ID conflict validation; partitioned outbox capacity by connector.
- Applied review fixes for duplicate test/checks, bounded bidirectional subprocess I/O and process-group cleanup, connector-local backoff, path resolution, private file creation modes, poison payload/cursor bounds, external-ID conflicts, and per-connector queue limits.
- Expanded root test coverage for SQLite rollback, connector profile isolation, malformed/conflicting events, unknown sends, idempotency-key payload fencing, adapter subprocess limits, heartbeat/scan timing, redirects, path resolution, and independent connector failure recovery. Final Windows-host run: 19 tests discovered, 18 passed, and 1 POSIX subprocess test skipped by platform; Python compilation and diff checks pass.
