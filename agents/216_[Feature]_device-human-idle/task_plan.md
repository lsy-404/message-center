# Task plan

- [x] Load repository instructions and inspect the device runtime scheduling and persistence boundaries.
- [x] Confirm the public worktree branch and assigned base commit.
- [x] Implement generic IOKit/CoreFoundation activity monitor with bounded callback state and thread-owned lifecycle.
- [x] Persist armed pause state atomically and fail closed on unknown or unhealthy monitoring.
- [x] Gate scan, command, and auto-wake paths while preserving outbox flush and explicit unavailable heartbeat.
- [x] Add focused `/test` coverage for HOME, touch, 180-second grace, rollback, monitor failure, restart, commands, and outbox behavior.
- [x] Run focused validation, review scoped diff, and commit locally without push.
