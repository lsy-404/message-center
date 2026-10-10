# Task plan

- [x] Inspect the public `main` worktree, runtime outbox, both Worker ingest routes, and existing runtime tests.
- [x] Record ACK and retry semantics from source before editing.
- [x] Implement a bounded FIFO prefix for contiguous attachment-free text rows while preserving single-row attachment handling.
- [x] Add temporary SQLite adversarial tests for ordering, route boundaries, byte bounds, ACK failures, and atomic deletion.
- [x] Run focused and relevant regression tests; review diff and commit locally.
