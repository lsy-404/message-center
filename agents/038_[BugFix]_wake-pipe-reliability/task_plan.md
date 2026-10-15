# Wake pipe reliability task plan

- [x] Review existing wake diagnostics, adapter pipe loop, and runtime tests.
- [x] Retry nonblocking pipe EAGAIN races within the existing adapter deadline and preserve process cleanup.
- [x] Classify wake adapter failures using a fixed redacted category allowlist.
- [x] Add deterministic tests for readiness races and category redaction.
- [x] Run focused device-runtime tests, inspect diff/privacy constraints, and commit the isolated change.
