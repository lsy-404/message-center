# Findings

- `run_adapter` makes both subprocess pipes nonblocking and waits for selector readiness, but the subsequent `os.write` and `os.read` calls can still raise `BlockingIOError` if readiness becomes stale. The loop already has an overall deadline and exception cleanup that terminates the owned process group.
- `Relay.ensure_active` currently collapses all adapter exceptions into the fixed reason `adapter_error`; malformed successful results are reported as `invalid_result`. Diagnostic output is already a fixed compact schema, so reason values can be categorized without exposing exception text.
- Live evidence supplied for this task shows one guarded wake call succeeded with `already_active` while the daemon had reported `adapter_error`; this supports repairing reliability but does not establish EAGAIN as the proven live root cause.

- Initial module-style unittest invocation failed because `test` is not a Python package; rerunning the test file directly succeeded.
- The deterministic race test uses fake process pipes and selector readiness so it runs on Windows as well as the device POSIX runtime; existing real-process deadline tests remain platform-gated.
