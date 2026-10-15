# QQ native attach recovery trigger

- [x] Read public runtime rules, prior wake/recovery audit, and current scan/wake state machine.
- [x] Confirm the private adapter's fixed native attach-failure contract with its owner.
- [x] Add strict scan-result classification and an attach-specific consecutive-failure recovery trigger without cursor, outbox, or command-ledger changes.
- [x] Keep the attach streak process-local and reset it on restart; do not reinterpret persisted generic source-failure counts.
- [x] Add focused tests for non-attach and mixed failures, cooldown, restart boundaries, PID changes, and uncertain sends.
- [x] Run focused and full public runtime tests, inspect only task-owned changes, and commit the task branch without pushing.
