# Progress

- Read the agent-mode workflow and repository instructions.
- Confirmed the assigned checkout is on `feature/device-auto-wake` and has a clean worktree.
- Located `Relay.pass_once`, adapter timeout routing, the sample config, README behavior notes, and root Python regression suite.
- Added opt-in `autoWake` validation for an exact QQ/WeChat pair, 20-second readiness operation timeout, once-per-minute cadence, strict bounded response checking, and source/command gating while preserving heartbeat and outbox progress.
- Added separate wake scan retry state; readiness recovery forces one bounded scan for each configured connector without resetting connector cloud retry state.
- Readiness expires 60 seconds after a valid response and is rechecked at scan, heartbeat source-health, command-poll, and final adapter-send decisions.
- Added seven regression tests and documented the public configuration and readiness contract.
- `python test/test_device_runtime.py`: 61 passed, 1 skipped.
- `python test/test_device_runtime_outbox_batch.py`: 10 passed.
- `git diff --check`: passed.
