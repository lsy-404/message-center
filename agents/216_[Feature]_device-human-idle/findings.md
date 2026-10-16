# Findings

- The public runtime's `Relay.pass_once()` flushes outbox before source reads and command polling. User-idle gating should leave outbox upload active, suppress scan/readiness auto-wake and command lease/send paths, and force heartbeat `offline` until a fresh source read after resume.
- `Relay` owns the runtime thread; the monitor should own its own CFRunLoop thread, callback object, IOKit client, and all CF references until explicit stop. Callback reads only event type and keyboard page/usage/down; Digitizer events count as activity without retaining coordinates or touch content.
- Root verified on-device ctypes loading for IOKit/CoreFoundation symbols and will perform native validation before installation. This implementation remains generic and does not touch QQ/SpringBoard injection or cleanup.
- Restart state must never cause early resume. Persist the armed marker atomically; absent, malformed, stale, or unknown state starts a fresh 180-second grace. Any monitor setup/callback failure remains fail-closed.
- The available device probe confirmed `IOHIDEventSystemClientUnscheduleWithRunLoop`; use that exact exported symbol. The event monitor proof is native callback availability only; physical HOME delivery remains unverified until a real button press is observed.
