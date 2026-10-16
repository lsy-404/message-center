# Findings

- The monitor publishes a bounded wall-clock lease with runtime PID and monitor identity. Cross-process monotonic timestamps are not comparable on this device build.
- Activity pauses scan, command polling, and auto-wake while outbox delivery continues; heartbeat reports offline until a fresh read.
- The relay carries `activityResumeCleanup` with a stable resume token and retains it across adapter errors until the private adapter acknowledges that exact token. The private adapter owns safe SpringBoard cleanup and QQ return.
- The private adapter returns completion metadata outside the public wake schema. The relay validates the exact token, clears its pending flag, then strips those fields before normal wake-response validation.
