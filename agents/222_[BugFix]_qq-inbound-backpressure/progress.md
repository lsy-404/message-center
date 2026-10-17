# Progress

- Confirmed public `main` and `origin/main` both resolve to `3f1e9fa286d2225b6c366c1e00e03ac9d4fd2fae`.
- Created `fix/qq-inbound-backpressure` in the requested isolated public worktree.
- Read agent-mode and repository instructions; inspected runtime and relevant test contracts. No production files changed yet.
- Added separate bounded exponential outbox retry state and routed only delivery failures through it. Kept source/command retry state unchanged; removed the outbox-row scan gate.
- Added regression tests proving a failed group-backup delivery remains queued while the source scan commits new data, and a full queue still skips scan without cursor advancement.
- Updated delivery batch replay tests to target outbox retry state.
- `python -m unittest discover -s test -p test_device_runtime.py`: 110 passed, 2 platform skips.
- `python -m unittest discover -s test -p test_device_runtime_outbox_batch.py`: 10 passed.
- `python -m unittest discover -s test`: 170 passed, 2 platform skips.
- `git diff --check` passes after normalizing the appended task-index line ending.
- Committed locally as `97e674a811c2d77a362b85bb7cb21682ce47453a` (`Fix inbound scan backpressure`); branch remains local and isolated.
- Follow-up coverage review found missing combined cases for ready auto-wake and source-read backoff after an upload failure. Added both tests without changing runtime code.
- Re-ran the full Python suite: 172 passed, 2 platform skips; `git diff --check` passes.

- Independent review found three integration blockers: trusted iOS `/var` alias resolution, an already-due pending generation not waking `wait()`, and transient watcher failures becoming permanently unavailable.
- `DirtyHint.wait()` now wakes from due pending state even if the event was polled before entering `wait()`. Minimum wake spacing remains enforced.
- Temporary queue, open, or reconcile failures now retire stale watcher descriptors and attempt reconstruction no more than once per five seconds. Permanent unavailability is reserved for unsupported APIs/platforms and malformed path input.
- Regression coverage includes the already-due wait case and recovery after a one-shot queue error. Targeted watcher suite: 8 passed; full public test discovery: 183 passed, 2 skipped. No device/cloud operation was performed.

- Implemented strict QQ canonical signal allowlist at `scan_profile` boundary.
- Added metadata and negative-path tests; no device/cloud access.
- Targeted host suites pass; pending commit for parent integration.

- Reviewed qdc4 cache validation and native helper/source lifecycle read-only.
- Recorded timeout/throw cleanup containment as a falsifiable hypothesis; no device/cloud access and no production change.
