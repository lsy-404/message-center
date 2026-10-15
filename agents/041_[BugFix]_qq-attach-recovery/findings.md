# Findings

- [Observed] `scan_profile` currently turns every explicit `sourceReadOk: false` response into `SourceReadError` and discards structured failure detail. `pass_once` increments the persisted generic source failure counter for all such errors and can request only `read_failure` recovery.
- [Observed] `ensure_active` validates a strict readiness response and currently supports only `reason: read_failure` for recovery calls.
- [Contract] The private adapter owner confirmed the only attach-recovery candidate is a fixed `nativeFailure` object with exactly `stage=attach`, `errorCode` in `{attach_failed, timeout}`, `dispatch=not_started`, and a positive integer `processId` captured before the failed attach. Missing, malformed, non-allowlisted, subprocess timeout, and page/read failures must not trigger attach recovery.
- [Constraint] No schema migration, cursor/outbox reset, command retry, or uncertain-send replay is allowed. A generic or mixed source error must break an attach-only consecutive streak.
- [Decision] Keep the attach-only consecutive streak in process memory and reset it on restart. Generic persisted source failure counts and their `read_failure` cooldown retain their existing meaning; a prior count cannot be treated as attach evidence. This conservative boundary avoids schema changes and ambiguous durable encoding.
- [Decision] Attach failures count only while the observed QQ process ID remains unchanged. A changed PID starts a new streak, and attach recovery forwards that PID as `observedPid` so a stale failure cannot close a replacement process.
