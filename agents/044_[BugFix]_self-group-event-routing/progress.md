# Progress

- Updated route selection and the background-group text constraint to exclude self-authored events.
- Added host coverage for self-group background routing with a staged image and for the normal event-ingest attachment linkage/direction result.
- Added Worker coverage for outbound/delivered ingestion and attachment linkage, plus rejection at the legacy backup endpoint with no backup row created.
- Verification: `python test/test_device_runtime.py` passed (84 tests, 2 skips); `node --experimental-sqlite --test test/worker-qq-send-reconciliation.test.mjs` passed.

- Clarified the runtime README that only inbound background group records use the backup endpoint. Added shared receipt-first/event-first reconciliation coverage for self-authored background group records.
- Verification: the Worker SQLite test passes with both ordering cases.
