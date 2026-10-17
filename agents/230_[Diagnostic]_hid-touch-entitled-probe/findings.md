# Findings

## Hypothesis and evidence boundary

The device listener observed 23,393 root events during a 290-second window after a user-confirmed physical touch, with root event types 1/3/12/13/20 and no type 11. A child-enabled 120-second diagnostic observed 9,669 events, no child types, and zero traversal errors. Separate read-only SecTask inspection of the current Python process reported no `com.apple.private.hid.client.event-monitor` entitlement (and no admin/dispatch variants), with no query error. This makes entitlement filtering a plausible hypothesis, but does not prove it caused the absent digitizer callbacks; event routing, caller class, OS behavior, or other filters may explain it.

## Safety contract

Apple's [IOHIDEventSystemMonitor entitlement plist](https://raw.githubusercontent.com/apple-oss-distributions/IOHIDFamily/main/tools/IOHIDEventSystemMonitor-Entitlements.plist) contains `com.apple.private.hid.client.event-monitor` alongside several more powerful entitlements. The diagnostic intentionally tests only that one key. Apple's full list shows precedent, not that the isolated key is sufficient for every process or OS version.

The diagnostic must be a separate short-lived executable and must not modify/sign system Python, SpringBoard, QQ, or the production runtime. Its only private entitlement is `com.apple.private.hid.client.event-monitor = true`. It must not carry admin, filter, dispatch, task-for-pid, or unrelated entitlements. It reads only callback event type and bounded child arrays, with no coordinates, field values, keyboard usages, text, device/service enumeration, raw event serialization, or per-event logs. It exits within 300 seconds, stops after 25,000 callbacks, and tears down callback registration, run-loop schedule, and client references on normal exit and SIGTERM/SIGINT.

The build signs the new executable with the existing pinned Procursus `ldid` tool and validates the embedded entitlement plist is exactly the single expected key; the [ldid manual](https://github.com/ProcursusTeam/ldid/blob/master/docs/ldid.1#L800-L812) documents `-e` extraction and [the `-S` entitlements-file form](https://github.com/ProcursusTeam/ldid/blob/master/docs/ldid.1#L921-L932). The helper tests whether adding the event-monitor entitlement changes callback type delivery in one controlled window; it cannot alone establish why production Python missed touch events, and it is not a production monitor candidate.
