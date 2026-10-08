# Progress

- Confirmed the device-runtime worktree was clean and fast-forwarded it to the current local `main` commit before beginning the change.
- Added fixed scan/send adapter deadlines of 60 and 90 seconds and made the Relay choose them from the request operation.
- Added root tests that capture the actual `run_adapter` deadline for a Relay scan and prove an adapter timeout during a leased send remains saved as uncertain with retry disabled.
- Validation: both focused tests passed; the complete runtime/profile Python suite passed 66 tests with one POSIX-only selector test skipped on Windows; `git diff --check` passed.
- Committed locally on the existing feature branch; did not push or deploy.
