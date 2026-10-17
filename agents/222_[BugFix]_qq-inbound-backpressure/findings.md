# Findings

- `pass_once()` currently derives `pending_connectors` from all outbox rows and refuses to scan any connector with a row. One persistent row can therefore stop source collection indefinitely.
- Upload failures in `flush_one()` call the same `failed()` method used by source reads and command polling. Its `retry_at` gate also suppresses ordinary scans.
- `scan_profile()` already enforces per-connector `outboxMaxBytes` before source reads and rechecks capacity inside the cursor/outbox transaction. It returns without committing the cursor if a page cannot fit. `pageLimit` is capped at 20; delivery batches are capped at 20 messages and `MAX_SCAN_RESPONSE` bytes.
- The narrow repair is a delivery-specific bounded exponential backoff, removal of the pending-row scan gate, and retention of the existing `scan_profile()` capacity/transaction checks. Delivery ACK remains the only condition that deletes outbox rows or counts as delivery success.
- `[focused unittest module import] -> tried dotted names under `test` -> the repository's test directory is not an importable package; switched to unittest discovery by filename.`
- `[outbox replay regression initially failed] -> an existing batch test reset the old shared `retry_at` after each negative ACK -> updated that test to clear only the new outbox retry deadline, preserving the delivery backoff contract.`

- Vnode notifications may be consumed before `wait()` starts; wake decisions must use current due/pending state, not require a generation edge within the current call.
- Watcher runtime faults are transient: close stale descriptors/queue and retry on a bounded timer. Keep unsupported platform/API and malformed supplied paths as permanent disable cases.
