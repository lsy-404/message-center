# Progress

- Root validated the descriptor-relative publisher in isolation on the actual iPad: five tests passed, none skipped, including mobile-owned ancestors, rejected symlinks/ownership/modes, parent rename without escape, and missing Library rejection. No production modules were replaced by that validation.
- Added Darwin constructor regressions for the metadata-only adapter bootstrap and fail-closed schema/path validation. The former global candidate is removed from the runtime contract after its actual QQ open returned EPERM.

- Confirmed dedicated worktree `feat/device-activity-mirror` at public baseline `c618472cc528c4ba89ae47afa1d1b1ed00b9d9e6`.
- Added optional mirror publication to `device_activity.py`; the original runtime-local state remains the primary write and controls local policy.
- The initial global-path candidate was superseded by the sandbox-derived bootstrap path after actual QQ access failed. Non-Darwin monitor behavior is unchanged.
- Added focused tests for v4 schema identity, start/activity/stop publication, fail-closed mirror failure, directory ownership/mode/no-symlink checks, target validation, and no implicit directory creation.
- Final focused host validation: `test_device_activity.py` passed 27 tests; `test_device_runtime.py` passed 114 tests with 2 platform skips. The five descriptor tests passed on the iPad. `git diff --check` passed.
- Committed as `50a4091cac1334cba1139e894172d72f3866b46e`.
- Actual QQ read of the new app-container mirror remains required before sender acceptance. Root performed isolated descriptor validation; these tests did not replace production modules.
