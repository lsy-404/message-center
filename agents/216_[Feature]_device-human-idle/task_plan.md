# Task plan

Implement on-device human activity gating and resume without changing message cursors, send budgets, or outbox delivery.

1. Consume verified HID HOME and digitizer events using the owned monitor.
2. Persist a strict bounded activity lease and distinguish safety grace from required app cleanup.
3. Gate runtime UI work and resume only after continuous idle, verified app state, and the existing wake budget.
4. Test activity, restart, lease, and cleanup behavior; leave live device validation to the parent.
