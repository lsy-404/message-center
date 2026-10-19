# Findings

- Current pass_once() command polling required health[connector_id] to be true, so a valid partial QQ scan could not reach command polling even though the runtime records partial_read and emits degraded heartbeats.
- The command gate independently checks activity pause, readiness, connector eligibility, source settle time, and scan freshness. Activity resume also marks the source as needing a fresh scan; the gate now explicitly retains that marker.
- process_command() repeats readiness/activity checks and preserves the native-operation uncertain guard. The adapter send contract and its per-target preflight were left unchanged.
- A partial scan is permitted to poll one command only while its source snapshot remains within the established freshness window. A failed scan clears partial_read; a complete scan restores normal healthy state.
