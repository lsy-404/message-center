# Task plan

Build a diagnostic-only, signed iOS HID event-type monitor with only the private event-monitor entitlement, to test whether the current process's missing entitlement explains absent digitizer callbacks.

- [x] Record the causal hypothesis and limits; missing entitlement is correlation, not proof.
- [x] Implement a bounded event-tree type counter with a host-testable API and no payload access.
- [x] Implement a short-lived native listener with 300-second and 25,000-callback hard caps, clean signal teardown, and aggregate-only status output.
- [x] Add an exact minimal entitlement plist and wire iOS arm64 compile/sign/entitlement verification into the existing native build workflow without changing the existing helper signing.
- [x] Add meaningful host tests for tree limits/malformed input and run available checks.
- [x] Keep the runtime-status probe on a clean branch based on public main, excluding the local no-entitlement control build.
- [x] Add a self-only query for the single HID event-monitor entitlement and the CS_OPS_STATUS restricted-entitlement validation bit.
- [x] Emit explicit availability and tri-state results without exposing PID, raw code-sign flags, or unrelated entitlements.
- [x] Add host tests for available, unavailable, true, false, and query-error cases.
- [x] Run available host checks; leave the iOS SDK build/CI and device execution to the parent.
- [x] Commit the scoped branch.
