# Task plan

Implement on-device human activity gating and resume without changing message cursors, send budgets, or outbox delivery.

1. Consume verified HID HOME and digitizer events using the owned monitor.
2. Persist a strict bounded activity lease and distinguish safety grace from required app cleanup.
3. Gate runtime UI work and resume only after continuous idle, verified app state, and the existing wake budget.
4. Test activity, restart, lease, and cleanup behavior; leave live device validation to the parent.

## Current static investigation

1. [x] Fast-forward this worktree to local main and inspect the current WebKit IOKit SPI wrapper.
2. [x] Query Apple OSS IOHIDFamily/IOKitUser paths and the old IOHIDFamily-308 tag for the C event declaration.
3. [x] Keep the initial probe root-type-only; extend the explicit diagnostic window to 300 seconds and atomically publish one-second aggregate status at a caller-specified validation path.
4. [x] Verify Apple user-space child-event bridging evidence and extend only the owned diagnostic to bounded, aggregate-only child-type counts.
5. [ ] Have the parent verify the target export and run the owned probe during an explicit touch window; production classification remains unchanged pending that evidence.
