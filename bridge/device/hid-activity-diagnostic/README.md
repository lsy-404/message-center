# HID activity diagnostic

This standalone iOS arm64 diagnostic listens for at most 300 seconds and at most 25,000 callback events. `ready: true` means API setup, callback registration, and run-loop scheduling completed; it does not prove that the system delivered any events. It prints one readiness/status JSON line, then one aggregate status line per second, and a final status line after callback unregistration, run-loop unscheduling, and client release. Send `SIGTERM` to end it early; it stops sampling and performs the same cleanup.

The executable is signed with exactly `com.apple.private.hid.client.event-monitor = true`. It is separate from the production runtime and native Frida helper. Do not add it to launchd or install it as a persistent service. The output contains only lifecycle metadata, callback counts, fixed root/child event-type counts, malformed-tree counts, and teardown status. It does not read event fields, coordinates, text, device/service lists, or raw event data.

Run with the default five-minute bound or provide a smaller bound:

```sh
./hid-activity-diagnostic
./hid-activity-diagnostic --seconds 60
```

This is a controlled diagnostic for event visibility, not a production monitor. An event-type difference under this entitlement would support, but by itself would not prove, entitlement filtering as the production cause.
