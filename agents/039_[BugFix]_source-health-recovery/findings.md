# Findings

- The public runtime accepts `ok=true` scan results, commits the returned cursor and messages, then records source health from `health == "online"`. A successful empty page is therefore representable, but there is no explicit field that distinguishes a failed native read from valid emptiness.
- Existing wake readiness has an exact four-key response schema and one-minute attempt interval. The private recovery owner confirmed it will retain that schema and use `ensure-active` for bounded activation; public recovery should trigger it only after repeated explicit native read failures.
- Source cursor inactivity is not evidence of a failed read. The public/private seam uses the existing health field: `health: "online"` is returned only after native discovery and the selected page both validate. A valid empty online page is success; non-online results are failure and their cursor/data are ignored.
- Public runtime already persists cursors, outbox, and command ledger in SQLite WAL. Recovery failure count/cooldown and settling deadline can be stored in a small SQLite table without modifying cursor, outbox, or send identity.
- Startup settling interval: 60 seconds after an activation attempt. During settling, do not scan or poll commands; continue outbox delivery and heartbeat with source freshness false. This avoids repeatedly invoking expensive native discovery while the apps settle.
- Recovery remains opt-in with `autoWake`; no force-kill, reboot, respring, cloud changes, or send retries are part of this implementation.
- CPU scope: public runtime now suppresses repeated scans during the 60-second activation settle window and retains exponential retry backoff; steady-state native conversation discovery frequency remains owned by the private adapter/cache work and was not changed here.
- Local verification: 100 isolated Python tests pass with one platform-specific skip. Real-device recovery and CPU impact remain unverified and require the coordinating task's authorized live validation.
- Follow-up review: a prior-success timestamp is not required for failure recovery; the explicit three-failure threshold and durable cooldown are sufficient on fresh installs.
- Backpressure (`scan_profile` returns `None`) is not source health evidence. It must leave timestamps and retry state unchanged and retain forced scan intent.
- Both scans and command polling must be gated by the persisted settle deadline after activation/readiness.
- Private wake safety review covered only commit `7393e62`; live app recovery is not demonstrated by unit tests. Its validated schema and private dispatch use constants, but malformed non-string/unhashable recovery values can currently raise during membership tests before the helper's broad catch.
