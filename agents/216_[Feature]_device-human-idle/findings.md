# Findings

- Activity state is version 4 and is accepted on restart only when it is a bounded regular non-symlink file with the complete typed schema.
- Missing, malformed, oversized, stale, or invalid state fails closed and requires the 180-second safety grace plus cleanup.
- A strict healthy/idle state with cleanupRequired false can restart through safety grace without consuming app-card cleanup budget.
- Actual physical HOME/touch and SpringBoard cleanup validation remain parent-owned.
