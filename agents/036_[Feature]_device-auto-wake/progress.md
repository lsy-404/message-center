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
- Public branch audit confirms `ready:false, attempted:true, reason:activation_submitted` is accepted and stays not-ready; no source scan or command polling follows from that result.
- Coordinator reports 73 runtime/outbox tests passed on iPad in 9.176 seconds without skips, and 73 passed on Windows with one platform skip. Device boot/Settings opening was followed by three minutes with outbox budget zero and no fresh cloud heartbeat; this is not resolved by the diagnostics change.
- Coordinator reports both connectors online at 22:57:21, with database totals of 17,004 QQ rows (+20) and 3,637 WeChat rows (+10).
- A bounded read-only SpringBoard probe around 22:57:55 confirmed valid saved split state, the expected foreground pair, screen on/unlocked, and no overlays. The receiver was paused for the probe and restored; no app activation occurred. Process identifiers are omitted.
- Short-window autonomous source-to-cloud sync remains verified. Locked-state operation, reboot recovery, and long-term operation remain unverified; the earlier heartbeat gap remains unexplained.
