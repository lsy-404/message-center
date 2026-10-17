# Task plan

Implement on-device human activity gating and resume without changing message cursors, send budgets, or outbox delivery.

1. Consume verified HID HOME and digitizer events using the owned monitor.
2. Persist a strict bounded activity lease and distinguish safety grace from required app cleanup.
3. Gate runtime UI work and resume only after continuous idle, verified app state, and the existing wake budget.
4. Test activity, restart, lease, and cleanup behavior; leave live device validation to the parent.

## Current static investigation

1. [x] Fast-forward this worktree to local main and keep it clean.
2. [x] Inspect the existing top-level HID classifier and activity timestamp gates without changing production code.
3. [x] Verify Apple OSS ownership of child collection and CoreFoundation array accessor ABI; record the C child getter as target-unverified.
4. [x] Add an owned, bounded aggregate-only HID monitor probe and host tests under `/test`; do not run it on a device.
5. [x] Send root exact target symbol/ABI validation gate and commit probe, tests, and audit records.
