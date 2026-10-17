# Findings

- Cleanup behavior and timing remain unchanged: a 5-second cleanup timeout cancels the active operation, then a 3-second grace precedes forced loop completion.
- The helper latches the first cleanup error's finite stage (`unload`, `detach`, `close`, `binary_output`, `not_started`, or `unknown`). A timeout records the pending cleanup stage before cancellation, even if cleanup later completes during grace.
- Runtime result envelopes now always include exact JSON boolean `cleanupIncomplete`. It is true only when `force_finish` fired; cleanup errors include the latched `cleanupStage`.
- The native contract suite validates the finite stages, the 5s/3s bounds, the timeout cancellation path, and JSON output semantics. No device test was run.
