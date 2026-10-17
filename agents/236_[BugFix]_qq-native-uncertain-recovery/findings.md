# Findings

- The helper result `await_result/timeout` with `cleanup_timeout/unload` and `dispatch=unknown` is distinct from `query_gate_pending`; it does not prove a live callback, but it is sufficient to fail closed for the observed QQ PID.
- A small durable sidecar records the blocked connector/PID so receiver restart cannot erase the unresolved state. The adapter receives that PID and refuses another native scan for the same PID before helper dispatch.
- Recovery reuses the existing PID-checked UI recovery, timeout, cooldown, startup grace, and fail-closed outcomes. The blocked state clears only after a subsequent scan succeeds; PID change alone does not clear it.
