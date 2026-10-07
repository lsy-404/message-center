# Findings

- The device's launchd rejects both the legacy nested JetsamMemoryLimit form and attempted top-level modern plist names; runtime currently remains at 6 MB.
- XNU defines `MEMORYSTATUS_CMD_SET_MEMLIMIT_PROPERTIES` (7), `GET_MEMLIMIT_PROPERTIES` (8), per-state limits in MB, and a fatal attribute bit. Setting only the launcher's own PID avoids global or other-process changes.
- Public XNU source did not establish whether memlimit state survives exec's task replacement. A point-in-time device run has now confirmed the post-exec Python GET returns 64/64 MB and fatal attributes 1/1 for the current launchd job.
- iOS authorization may reject the private memorystatus operation. The launcher must fail closed and must not add entitlements or use another privilege path.
- Existing artifact workflow signs the Frida helper ad hoc and validates CS_ADHOC. Extend it to build and validate a separate libSystem-only binary while retaining the Frida helper unchanged.
- Dopamine's configurable jetsam multiplier is not a per-job limit interface; no built-in targeted command was found.
- The Windows host has no Apple iOS SDK, so the actual iOS arm64 link/sign check must be established by the existing macOS workflow. The host-stub C harness is compiled and run locally.
- GitHub Actions run 37690830081 succeeded: host-stub contract tests, iOS 15+ arm64 compilation, ad-hoc CodeDirectory checks for both binaries, and artifact upload passed.
- Device report: launcher SHA-256 `9234052e605b5c7599b92b0e28c1d55dd6e95d79a082b7ef51ee1f37a0ac8684`; standard jailbreak program-directory execution succeeded. Python post-exec GET returned active/inactive 64 MB with attributes 1/1. The configured receive-only job was running with RSS 21248 KiB, CPU 0%, and empty logs. This is a startup snapshot, not long-duration or background-stability evidence.
