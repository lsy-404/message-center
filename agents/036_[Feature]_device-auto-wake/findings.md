# Findings

- The public Python runtime owns scan, outbox delivery, heartbeat, and command polling. Adapter operations are sent as one JSON request to the configured private adapter.
- The opt-in readiness operation must use a dedicated 20-second deadline and a strict bounded response contract. Public code contains no device identifiers, native endpoints, or private adapter details.
- A successful wake request only authorizes a subsequent bounded source scan; source health remains determined by that scan.
- While wake readiness is false, durable outbox delivery and heartbeats remain independent. Source scans and cloud command polling are gated.
- Wake recovery must bypass source scan interval/backoff once without clearing cloud delivery or command retry state.
- Contract audit: `ready:false`, `attempted:true`, `reason:"activation_submitted"` is valid. The lowercase bounded reason pattern accepts it; the only prohibited flag combination is `ready:true` with `attempted:true`. This status remains not-ready, so source scans and command polling stay gated until a later readiness result and fresh source scan.
- Coordinator-reported device suite evidence: 73 public runtime/outbox tests passed on iPad in 9.176 seconds with no skips; Windows reported 73 tests with one platform skip. This is regression evidence, not proof of autonomous source synchronization.
- The initial installed run booted and opened Settings, then after three minutes the outbox budget reached zero with no fresh cloud heartbeat. The later result below demonstrates a subsequent short-window source-to-cloud sync; it does not explain the earlier anomaly.
- Coordinator-reported bounded acceptance: autonomous activation at 22:54:16; independent readiness at 22:55:47 confirmed the saved QQ/WeChat split view and both foreground processes; at 22:56:35 both source cursors advanced, 24 outbox rows existed, and two ledger entries were done without change; an independent remote database read at 22:56:43 confirmed 10 fresh cloud rows per channel, created at 22:56.
- Follow-up at 22:57:21 reported both QQ and WeChat online. Independent database totals were 17,004 QQ rows (+20) and 3,637 WeChat rows (+10).
- A bounded read-only SpringBoard probe around 22:57 confirmed the saved split configuration was valid, exactly one saved QQ/WeChat pair matched, both app processes were foreground, the screen was on and unlocked, and overlays were absent. The receiver was paused briefly for the probe and restored afterward; no app activation was performed. Process identifiers are omitted.
- Short-window autonomous source-to-cloud sync is verified from the reported evidence. The earlier heartbeat gap remains unexplained. Locked-state operation, reboot recovery, and long-term operation remain unverified.
