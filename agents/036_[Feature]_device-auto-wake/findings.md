# Findings

- The public Python runtime owns scan, outbox delivery, heartbeat, and command polling. Adapter operations are sent as one JSON request to the configured private adapter.
- The opt-in readiness operation must use a dedicated 20-second deadline and a strict bounded response contract. Public code contains no device identifiers, native endpoints, or private adapter details.
- A successful wake request only authorizes a subsequent bounded source scan; source health remains determined by that scan.
- While wake readiness is false, durable outbox delivery and heartbeats remain independent. Source scans and cloud command polling are gated.
- Wake recovery must bypass source scan interval/backoff once without clearing cloud delivery or command retry state.
- Contract audit: `ready:false`, `attempted:true`, `reason:"activation_submitted"` is valid. The lowercase bounded reason pattern accepts it; the only prohibited flag combination is `ready:true` with `attempted:true`. This status remains not-ready, so source scans and command polling stay gated until a later readiness result and fresh source scan.
- Coordinator-reported device suite evidence: 73 public runtime/outbox tests passed on iPad in 9.176 seconds with no skips; Windows reported 73 tests with one platform skip. This is regression evidence, not proof of autonomous source synchronization.
- The initial installed run booted and opened Settings, then after three minutes the outbox budget reached zero with no fresh cloud heartbeat. The later result below demonstrates a subsequent short-window source-to-cloud sync; it does not explain the earlier anomaly.
- Coordinator-reported bounded acceptance: autonomous activation at 22:54:16; independent readiness at 22:55:47 confirmed the saved QQ/WeChat split view and both foreground processes; at 22:56:35 both source cursors advanced, 24 outbox rows existed, and two ledger entries were done without change; an independent remote database read at 22:56:43 confirmed 10 fresh cloud rows per channel, created at 22:56. QQ was online; the WeChat heartbeat was still pending refresh.
- Short-window autonomous source-to-cloud sync is verified from that reported evidence. Locked state, reboot recovery, long-term operation, and the pending WeChat heartbeat refresh remain unverified; no cause is assigned to the earlier anomaly.
