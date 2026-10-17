# Progress

- Fixed malformed and oversized activity-state parsing to return fail-closed unknown state rather than crashing monitor startup.
- Added negative coverage for incomplete, extra-field, wrong-version/type, invalid-counter/timestamp, non-regular, symlink, and oversized state; strict healthy-false idle state remains restartable.
- Added coverage for dangling symlink and state lookup/read errors; only an absent path receives first-run grace without cleanup intent.
- Public focused suites passed: test_device_activity.py (24) and test_device_runtime.py (108, 2 skipped).
- Static follow-up: task branch fast-forwarded to local main; no production code changed. The classifier is top-level only, no child API evidence is present, and lastActivityAt timing cannot be established from the supplied counters. Diagnostic evidence requirements and a bounded aggregate-only design are recorded in findings.md.
- Primary Apple OSS sources were checked for event child ownership and CoreFoundation array accessor behavior. Added `test/device_hid_aggregate_probe.py`, an owned, 30-second maximum runloop monitor that reports only fixed aggregate root/parent-child type counts and has depth, per-event node, and total callback caps. It reads no payload, coordinates, usage values, or text and releases the monitor client after unregister/unschedule. Device export validation is left to the parent.
- Added host tests for aggregate counts, cycles/depth/width bounds, option bounds, and refusal to start on a non-Darwin host. `python test/test_device_hid_aggregate_probe.py -v` passed (5 tests); `py_compile` and `git diff --check` passed. The global gitignore excludes `/test`, so the two test files must be force-added when committing.
