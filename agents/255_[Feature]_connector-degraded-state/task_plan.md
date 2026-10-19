# Connector degraded state plan

- [x] Inspect Worker heartbeat, snapshot, command preflight, and UI state consumers.
- [x] Implement strict online/offline/degraded state handling without changing auth or freshness semantics.
- [x] Add focused Worker and UI tests for degraded, invalid, offline, and stale online behavior.
- [x] Run focused tests and UI typecheck/build using existing local dependency fixtures.
- [x] Review diff and commit the isolated task branch.