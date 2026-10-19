# Findings

- The helper already maps `FridaSessionDetachReason` to a finite allowlist and emits `detachReason`.
- A detached signal can arrive while cleanup is already in progress. The current callback records the reason and returns; the later unload callback may call `detach_session`.
- Added `detachSignalMs` (monotonic elapsed time) and `detachDuringCleanup` (strict Foundation boolean) only when a signal is observed. No raw Frida reason or crash object is serialized.
- Added `detach_signal_seen` to make the later cleanup continuation skip a redundant `frida_session_detach` call and proceed to the existing manager-close callback. The signal callback does not close the manager directly because that could race an in-flight unload/detach callback.
- No public evidence proves that a cleanup timeout or target death caused the QQ exit; the telemetry remains diagnostic only.
- Private wrapper contract for the companion change: accept `phaseElapsedMs.detachSignalMs` as a nonnegative bounded integer under the existing phase limit, `detachDuringCleanup` as a strict JSON boolean, and the existing finite `detachReason` enum. Reject booleans, negative/fractional/out-of-range elapsed values, and unknown reason strings.
