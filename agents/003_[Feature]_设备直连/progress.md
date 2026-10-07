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
- Fixed first-scan scheduling to use a negative-infinity monotonic sentinel and added a zero-origin monotonic clock regression test. Current Windows-host run: 20 tests discovered, 19 passed, and 1 POSIX-only subprocess test skipped; Python compilation and diff checks pass.
- Added explicit scan page and byte budgets with response-envelope validation, and round-robin outbox delivery that continues to a healthy connector after another fails. Current Windows-host run: 24 tests discovered, 23 passed, and 1 POSIX-only subprocess test skipped; Python compilation and diff checks pass.
- Added a byte-aware adapter pagination regression test showing continuation cursor advancement under the 900 KiB response cap. Final run: 25 tests discovered, 24 passed, and 1 POSIX-only subprocess test skipped; Python compilation and diff checks pass.
