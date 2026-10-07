# Progress

- Loaded agent-mode and reviewed project instructions, current main commit, Worker connector protocol, R2 upload route, normal event attachment binding, and group-text-backups POST.
- Confirmed the device-runtime worktree was clean and created `feature/inbound-media` from `cfa7792`.
- Sent the safe staging and attachment field contract to the project owner for private adapter integration.
- Added bounded local staging validation, remaining-byte signaling, per-connector outbox media accounting, fixed-size HTTPS file streaming, retry-safe metadata posting, and cleanup of unreferenced files to the public runtime.
- Extended only the existing group-text-backups POST to validate uploaded image rows, persist normalized attachment metadata, bind the attachment, and preserve the background-only queue class.
- Added runtime and Worker integration coverage for cursor freeze on invalid media, media capacity accounting, chunk bounds and headers, ACK retention on upload failure, group image binding/deduplication, and missing-upload rejection.
- Validation: `python -m unittest discover -s test -v` passed 44 tests with one platform-specific skip; JavaScript syntax checks, worker smoke tests, inbox refresh tests, and Worker schema integration tests passed. Diff and audit constraints checked before local commit.
