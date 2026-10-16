# Task 047: Forward the local QQ source cursor to send

## Objective

Pass the latest cursor stored for the active QQ connector and profile to the private send adapter locally, without adding it to Worker command payloads or logs.

## Plan

- [x] Verify the assigned public worktree is clean and read project rules and the agent-mode workflow.
- [x] Trace cursor persistence, active connector/profile selection, command ledger replay, and one-shot adapter invocation.
- [x] Add a strict local cursor loader keyed by both connector ID and profile, with the existing durable-cursor size bound.
- [x] Include the cursor only in QQ send adapter requests; fail closed before native dispatch for mismatched scope or missing/invalid state.
- [x] Add tests for matching scope, wrong connector/profile, missing/oversized cursor, no cloud propagation, and done-command replay without redispatch.
- [x] Run focused and full public runtime tests, inspect the diff, and commit without pushing.

## Boundaries

No device/cloud calls, Worker envelope changes, cursor writes/resets, schema changes, logging of cursor contents, or adapter retries after uncertain dispatch.
