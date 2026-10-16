# Progress

- Fixed malformed and oversized activity-state parsing to return fail-closed unknown state rather than crashing monitor startup.
- Added negative coverage for incomplete, extra-field, wrong-version/type, invalid-counter/timestamp, non-regular, symlink, and oversized state; strict healthy-false idle state remains restartable.
- Public focused suites passed: test_device_activity.py (23) and test_device_runtime.py (108, 2 skipped).
