# Findings

- The monitor publishes a bounded wall-clock lease with runtime PID and monitor identity. Cross-process monotonic timestamps are not comparable on this device build.
- Activity pauses scan, command polling, and auto-wake while outbox delivery continues; heartbeat reports offline until a fresh read.
- The relay now carries a one-shot `activityResumeCleanup` flag on the first `ensure-active` request after a paused-to-idle transition. The private adapter owns safe SpringBoard cleanup and QQ return.
