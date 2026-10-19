# Partial scan command readiness

- [x] Review the existing partial-read state, heartbeat freshness gates, and per-command send preflight.
- [x] Add the narrow partial-read command gate without weakening activity, readiness, freshness, eligibility, capability, budget, or native-uncertain checks.
- [x] Add runtime tests for fresh partial dispatch and stale, paused, failed, or blocked cases.
- [x] Run focused and full runtime/activity tests, record findings and validation, and commit the isolated change.
