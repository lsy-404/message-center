# Plan

- [x] Confirm the existing native-cleanup-diagnostic worktree is isolated, clean, and based on public main containing the prior cleanup metadata change.
- [x] Encode `gboolean hard_timeout` explicitly as Objective-C `@YES` or `@NO`.
- [x] Add an Objective-C Foundation runtime test and CI step that round-trips equivalent integer 0/1 values through JSON and checks Python's strict boolean types.
- [x] Run available host tests, commit locally, and report native-CI validation boundary.
