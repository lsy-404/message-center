# Findings

- The public Python runtime owns scan, outbox delivery, heartbeat, and command polling. Adapter operations are sent as one JSON request to the configured private adapter.
- The opt-in readiness operation must use a dedicated 20-second deadline and a strict bounded response contract. Public code contains no device identifiers, native endpoints, or private adapter details.
- A successful wake request only authorizes a subsequent bounded source scan; source health remains determined by that scan.
- While wake readiness is false, durable outbox delivery and heartbeats remain independent. Source scans and cloud command polling are gated.
- Wake recovery must bypass source scan interval/backoff once without clearing cloud delivery or command retry state.
