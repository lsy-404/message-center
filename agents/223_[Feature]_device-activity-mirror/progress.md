# Progress

- Confirmed dedicated worktree `feat/device-activity-mirror` at public baseline `c618472cc528c4ba89ae47afa1d1b1ed00b9d9e6`.
- Added optional mirror publication to `device_activity.py`; the original runtime-local state remains the primary write and controls local policy.
- Wired Darwin-native monitor request fields to the fixed mirror path. Non-Darwin monitor behavior is unchanged.
- Added focused tests for v4 schema identity, start/activity/stop publication, fail-closed mirror failure, directory ownership/mode/no-symlink checks, target validation, and no implicit directory creation.
- Validation: `test_device_activity.py` passed 29 tests; `test_device_runtime.py` passed 112 tests with 2 platform skips. Python compile checks and `git diff --check` passed.
- Committed as `50a4091cac1334cba1139e894172d72f3866b46e`.
- Device sandbox readability remains unverified; no device access was performed.
