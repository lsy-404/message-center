# Findings

- The current runtime accepts `sourceReadOk: false` by raising before cursor/outbox processing, so any safe scheduling-pointer-only candidate is lost.
- `sourceReadOk: true` commits the response and unconditionally calls `source_read_succeeded`, updating last-success and clearing the source-failure streak even when `health` is degraded.
- A `health: degraded` response already commits validated progress and makes `scan_profile` return not-online, used for thumbnail backlog. The new contract must preserve that behavior for complete page reads.
- Partial QQ scan results need their own strict statistics and update path: reset global failure continuity for a safely processed partial result, update last-success only if at least one page completed, return degraded, and never trigger whole-QQ recovery.
- Failed results retain existing SourceReadError/quarantine behavior and must not commit cursor/outbox/profile changes.
- The partial status envelope is intentionally source-agnostic at public-runtime boundaries: page aliases and individual exception details are omitted; exact aggregate counts are sufficient to enforce persistence and health semantics.
- `pass_once` updates connector health from `scan_profile`'s boolean result and sends offline heartbeat when the result is degraded, while still acknowledging the dirty generation after committed partial progress.
