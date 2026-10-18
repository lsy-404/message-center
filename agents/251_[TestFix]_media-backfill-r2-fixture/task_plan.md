# Media backfill R2 fixture alignment

- [x] Reproduce the standalone fixture mismatch reported by the independent test run.
- [x] Match the schema fixture's exact-length stream and R2 checksum return contract in the media backfill test only.
- [x] Preserve existing direct/group attachment, avatar, conflict, and integrity assertions.
- [x] Run media backfill, Worker schema, and QQ send reconciliation tests; review and commit the test-only diff.
