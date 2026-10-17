# Findings

- `pass_once()` currently derives `pending_connectors` from all outbox rows and refuses to scan any connector with a row. One persistent row can therefore stop source collection indefinitely.
- Upload failures in `flush_one()` call the same `failed()` method used by source reads and command polling. Its `retry_at` gate also suppresses ordinary scans.
- `scan_profile()` already enforces per-connector `outboxMaxBytes` before source reads and rechecks capacity inside the cursor/outbox transaction. It returns without committing the cursor if a page cannot fit. `pageLimit` is capped at 20; delivery batches are capped at 20 messages and `MAX_SCAN_RESPONSE` bytes.
- The narrow repair is a delivery-specific bounded exponential backoff, removal of the pending-row scan gate, and retention of the existing `scan_profile()` capacity/transaction checks. Delivery ACK remains the only condition that deletes outbox rows or counts as delivery success.
- `[focused unittest module import] -> tried dotted names under `test` -> the repository's test directory is not an importable package; switched to unittest discovery by filename.`
- `[outbox replay regression initially failed] -> an existing batch test reset the old shared `retry_at` after each negative ACK -> updated that test to clear only the new outbox retry deadline, preserving the delivery backoff contract.`

- Vnode notifications may be consumed before `wait()` starts; wake decisions must use current due/pending state, not require a generation edge within the current call.
- Watcher runtime faults are transient: close stale descriptors/queue and retry on a bounded timer. Keep unsupported platform/API and malformed supplied paths as permanent disable cases.

## QQ receive-hint allowlist follow-up

The generic DirtyHint watcher remains path-agnostic. The QQ scan boundary now accepts only the canonical JBROOT-derived `signals/changed.json` and `signals` pair, verifies no symlink at each accepted node, and checks root-owned 0755 state plus mobile-owned 0700/0600 signal state. Invalid or missing metadata clears the watcher after a durable scan, allowing a later valid scan to restore it. The receive-hint field is removed before cursor/outbox persistence, so local paths do not enter durable state.

Host evidence: `test_device_runtime.py` passed 121 tests (2 skipped); `test_device_runtime_dirty_hint.py` passed 8 tests. Added positive canonical metadata, arbitrary-path rejection/clear, and symlinked-signal-directory rejection coverage.

## Private QQ native lifecycle review

The current qdc4 discovery cache is recognized by `native_helper.py`; the older qdc1-only diagnostic is stale evidence. A 60-second cache TTL can increase full discovery work during 60-second inactive scans, but there is no evidence here that it caused the QQ exit.

The source has a real timeout containment gap to verify: `runGatedNativePage` delivers a timeout before `canFinishNativeWork()` becomes true. If the native callback never arrives, `queueCleanup()` returns while the outer helper can proceed to unload/detach. Synchronous native throw without a callback similarly delivers `native-page-invocation-uncertain` without queueing cleanup. The associated query token is process-scoped, so a leaked token should be observable on the next helper as `native-query-busy` with the existing pending diagnostic. No claim of root cause is made without that sequence.

Existing build_scan tail only recognizes pending gate state after a later readPage call; it does not keep a timed-out native operation alive and does not prevent helper unload. `Script.pin` is released only in the deferred cleanup path and is not an external helper keepalive contract. The minimum safe direction is to make helper lifetime conditional on native cleanup completion, with one bounded containment path for an unresolved operation; never eternalize every scan.

Required phase evidence: target PID, helper stages through unload/detach/close, dispatch state, cleanup code, and the existing pending snapshot fields (operation, stage, callbackSeen, nativeFrames, parserTasks, nativeCallOutcome, nativeCallErrorClass, cleanupReason). Distinguish helper attach failure (`dispatch=not_started`) from JS/native page failure.

## Containment qualification

Frida `Script.pin()` is called after gate acquisition and before native dispatch, so the static review cannot claim that Promise delivery itself proves unsafe script unload or callback invalidation. The helper must be checked for its cleanup-cancel and hard-timeout behavior. The source-level fact remains narrower: timeout/throw paths can leave native work or the process-scoped gate pending, and the next helper can expose that through `native-query-busy` plus `pendingOperation`; whether the helper preserves the pinned script until that state clears is unverified. A Node stub binding was attempted but did not reproduce a valid Frida gate transition, so it is not evidence of runtime unload behavior.

## Lifecycle evidence correction

The existing source-bound Node lifecycle suite passes 19 tests. It demonstrates that timeout, no-callback, parser-schedule failure, and callback-exit failure keep `Script.pin()` active, retain the pending gate, and defer `unpin` until cleanup can finish. The review therefore distinguishes a helper-issued unload request from actual script destruction: current evidence proves the former may be requested while native work is pending, but does not prove that Frida destroyed the pinned script or invalidated a native callback. A real QQ exit remains un-attributed without sanitized helper cleanup phases or a subsequent `native-query-busy` plus pending snapshot sequence.
