# Findings

- The public Python runtime owns scan, outbox delivery, heartbeat, and command polling. Adapter operations are sent as one JSON request to the configured private adapter.
- The opt-in readiness operation must use a dedicated 20-second deadline and a strict bounded response contract. Public code contains no device identifiers, native endpoints, or private adapter details.
- A successful wake request only authorizes a subsequent bounded source scan; source health remains determined by that scan.
- While wake readiness is false, durable outbox delivery and heartbeats remain independent. Source scans and cloud command polling are gated.
- Wake recovery must bypass source scan interval/backoff once without clearing cloud delivery or command retry state.
- Contract audit: `ready:false`, `attempted:true`, `reason:"activation_submitted"` is valid. The lowercase bounded reason pattern accepts it; the only prohibited flag combination is `ready:true` with `attempted:true`. This status remains not-ready, so source scans and command polling stay gated until a later readiness result and fresh source scan.
- Coordinator-reported device suite evidence: 73 public runtime/outbox tests passed on iPad in 9.176 seconds with no skips; Windows reported 73 tests with one platform skip. This is regression evidence, not proof of autonomous source synchronization.
- End-to-end feature acceptance remains pending an autonomous test that demonstrates a fresh source scan and cloud sync. The coordinator reported the installed runtime booted and Settings opened, then after three minutes the outbox budget reached zero with no fresh cloud heartbeat; the diagnostic commits do not establish the cause or fix it.
