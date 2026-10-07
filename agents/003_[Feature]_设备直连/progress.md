# Progress

- Read agent-mode workflow and project rules.
- Inspected `bridge/src/unified-relay.ts`, `bridge/src/adapters/device.ts`, `cloudflare-worker/CONNECTOR_PROTOCOL.md`, Worker event and command handlers, and existing cursor/idempotency tests.
- Added standard-library Python runtime and private adapter contract with one relay process for multiple connector identities.
- Added bounded transactional SQLite outbox/cursors, direct HTTPS requests with redirects disabled, per-connector heartbeat and scan pacing, serialized command polling, lease renewal, and fail-closed idempotency ledger.
- Added an optional launchd example without installing or enabling a service.
- Ran `python -m unittest discover -s test -v`: all 8 tests passed; `python -m py_compile bridge/device-runtime/device_runtime.py` passed; `git diff --check` passed.
- Added attachment-page cursor safety and startup lock checks; final validation passed with all 9 tests. Committed as `95cac64` on `feature/device-runtime`.
