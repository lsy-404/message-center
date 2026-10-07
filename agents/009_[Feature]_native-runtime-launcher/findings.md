# Findings

- The device's launchd rejects both the legacy nested JetsamMemoryLimit form and attempted top-level modern plist names; runtime currently remains at 6 MB.
- XNU defines `MEMORYSTATUS_CMD_SET_MEMLIMIT_PROPERTIES` (7), `GET_MEMLIMIT_PROPERTIES` (8), per-state limits in MB, and a fatal attribute bit. Setting only the launcher's own PID avoids global or other-process changes.
- Public XNU source does not establish that memlimit state survives exec's task replacement. The launcher must set then GET-verify before exec, and device testing must query again after Python starts.
- iOS authorization may reject the private memorystatus operation. The launcher must fail closed and must not add entitlements or use another privilege path.
- Existing artifact workflow signs the Frida helper ad hoc and validates CS_ADHOC. Extend it to build and validate a separate libSystem-only binary while retaining the Frida helper unchanged.
- Dopamine's configurable jetsam multiplier is not a per-job limit interface; no built-in targeted command was found.
- The Windows host has no Apple iOS SDK, so the actual iOS arm64 link/sign check must be established by the existing macOS workflow. The host-stub C harness is compiled and run locally.
- The sample launchd job is intentionally marked operationally unverified: its launcher fails closed unless the syscall succeeds and its own GET reports exact 64/64 MB fatal properties; post-exec persistence still requires a device check.
