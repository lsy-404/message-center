# Findings

- `run_adapter` makes both subprocess pipes nonblocking and waits for selector readiness, but the subsequent `os.write` and `os.read` calls can still raise `BlockingIOError` if readiness becomes stale. The loop already has an overall deadline and exception cleanup that terminates the owned process group.
- `Relay.ensure_active` currently collapses all adapter exceptions into the fixed reason `adapter_error`; malformed successful results are reported as `invalid_result`. Diagnostic output is already a fixed compact schema, so reason values can be categorized without exposing exception text.
- Live evidence supplied for this task shows one guarded wake call succeeded with `already_active` while the daemon had reported `adapter_error`; this supports repairing reliability but does not establish EAGAIN as the proven live root cause.

- Initial module-style unittest invocation failed because `test` is not a Python package; rerunning the test file directly succeeded.
- The deterministic race test uses fake process pipes and selector readiness so it runs on Windows as well as the device POSIX runtime; existing real-process deadline tests remain platform-gated.

- Source audit found the runtime plist template explicitly enables `LowPriorityIO` alongside `Nice=10`; the launcher still independently sets and verifies its 64 MiB active/inactive fatal memory limit.
- Apple primary source: [launchd.plist manual](https://github.com/apple-oss-distributions/launchd/blob/main/man/launchd.plist.5) says `LowPriorityIO` asks the kernel to treat daemon filesystem I/O as low priority. It also says `Standard` is equivalent to an unspecified `ProcessType`, so adding that value is not a meaningful correction.
- New live evidence reports receiver startup exceeding three minutes while a normal SSH Python probe completed in 1–3 seconds. This motivates removing only `LowPriorityIO` in the template as a controlled trial; it does not prove that I/O priority caused the delay.

- Live follow-up shows removing `LowPriorityIO` alone did not restore responsiveness: the new receiver remained at 1.4 MiB RSS after 83 seconds with no first wake; the prior PID was still present at 183 seconds and 15 MiB. This weakens the low-priority-I/O hypothesis as a sufficient explanation.
- The next controlled candidate is `ProcessType=Interactive` for this dedicated, user-requested receiver: bounded synchronous helpers and foreground restoration require timely response, and the runtime uses direct subprocess pipes plus HTTPS rather than an XPC activity path that would promote an Adaptive job. This remains a candidate pending root-owned live verification.
- Apple primary `launchd.plist` documentation says Interactive uses app-equivalent resource limits and should be reserved for jobs whose responsiveness depends on it and cannot be made Adaptive. The existing native launcher still enforces the separately verified 64 MiB active/inactive fatal limits; Nice, throttle interval, app processes, data, and device runtime budgets are unchanged.
