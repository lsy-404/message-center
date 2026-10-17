# Task plan

Build a diagnostic-only, signed iOS HID event-type monitor with only the private event-monitor entitlement, to test whether the current process's missing entitlement explains absent digitizer callbacks.

- [x] Record the causal hypothesis and limits; missing entitlement is correlation, not proof.
- [x] Implement a bounded event-tree type counter with a host-testable API and no payload access.
- [x] Implement a short-lived native listener with 300-second and 25,000-callback hard caps, clean signal teardown, and aggregate-only status output.
- [x] Add an exact minimal entitlement plist and wire iOS arm64 compile/sign/entitlement verification into the existing native build workflow without changing the existing helper signing.
- [x] Add meaningful host tests for tree limits/malformed input and run available checks.
- [ ] Commit the scoped branch and leave device installation/testing to the parent.
