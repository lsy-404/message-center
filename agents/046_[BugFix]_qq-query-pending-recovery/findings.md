# Findings

- The public runtime strictly validates the four-field nativeFailure shape and an integer process ID greater than one.
- The pending streak is process-local, QQ-only, same-PID, and resets on success, unrelated source errors, PID changes, and process restart.
- Recovery reuses existing source-recovery cooldown/budget and passes the observed PID for the switcher’s existing recheck; it does not touch message dispatch.
- Full public test discovery passed: 130 tests, 2 skipped.
