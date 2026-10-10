# Task plan: late inbound image replay

## Goal
Add a Worker regression test showing that a placeholder inbound message can be enriched with a later uploaded image while keeping its stable message ID and queue entry.

## Scope
- Extend the existing `cloudflare-worker/worker/schema-test.mjs` harness only.
- Use an uploaded inbound image bound to the same connector and conversation.
- Assert canonical message identity, attachment link/state, and no duplicate message or agent queue row.
- Do not change production behavior unless the test demonstrates a defect.

## Validation
Run `node worker/schema-test.mjs` from `cloudflare-worker`.
