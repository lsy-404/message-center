# Findings

- The `cursors` table is keyed by `(connector_id, profile)` and only `scan_profile` commits successful adapter cursor results. That persisted row is the local authoritative source requested for QQ send-time identity discovery.
- `process_command` checks the command ledger before lease/send work. `done` replays the stored completion and returns without invoking the adapter; `started` likewise returns uncertain without redispatch. Cursor forwarding must remain after these branches.
- The QQ send adapter call is local subprocess JSON, separate from the Worker `/complete` request. The cursor must be added only to that local request and never to command fingerprint, completion payload, or logs.
- The durable cursor limit is 65,536 UTF-8 bytes, enforced by `source_cursor`; forwarding should reject malformed or oversized stored values without altering the row.
- The send cursor loader reads only the exact active `(connector_id, profile)` row, rejects a connector/profile mismatch, missing row, invalid v1 cursor shape, or a serialized value beyond the existing 65,536-byte limit. It does not mutate cursor state.
- The complete cursor is added only to the local QQ adapter request after ledger replay and readiness checks. It is absent from WeChat requests, command fingerprints, and Worker completion payloads.
- Cursor preflight failures occur before `adapter_call`, are recorded as terminal nonretryable outcomes, and cannot cause a second send. A completed idempotency key replays its saved result even if the cursor is later absent.
- Focused runtime suite passed 98 tests (2 skipped); full public Python test suite passed 134 tests (2 skipped).
