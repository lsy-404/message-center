# HID activity diagnostic

This standalone iOS arm64 diagnostic listens for at most 300 seconds and at most 25,000 callback events. `ready: true` means API setup, callback registration, and run-loop scheduling completed; it does not prove that the system delivered any events. It prints one readiness/status JSON line, then one aggregate status line per second, and a final status line after callback unregistration, run-loop unscheduling, and client release. Send `SIGTERM` to end it early; it stops sampling and performs the same cleanup.

The executable is signed with exactly `com.apple.private.hid.client.event-monitor = true`. It is separate from the production runtime and native Frida helper. Do not add it to launchd or install it as a persistent service. The output contains only lifecycle metadata, callback counts, fixed root/child event-type counts, malformed-tree counts, teardown status, and three self-status fields: whether the two single-entitlement SecTask functions resolved, the queried HID entitlement value (`true`, `false`, or `null` when unavailable/unknown), and the `CS_ENTITLEMENTS_VALIDATED` status bit (`true`, `false`, or `null` when unavailable/unknown). The entitlement query requests only `com.apple.private.hid.client.event-monitor`; the code-sign query reads only this process's status via `csops(CS_OPS_STATUS)`. The code-sign bit does not prove that the specific HID entitlement was granted. It does not read event fields, coordinates, text, unrelated entitlements, device/service lists, or raw event data.

Run with the default five-minute bound or provide a smaller bound:

```sh
./hid-activity-diagnostic
./hid-activity-diagnostic --seconds 60
```

This is a controlled diagnostic for event visibility, not a production monitor. An event-type difference under this entitlement would support, but by itself would not prove, entitlement filtering as the production cause.
