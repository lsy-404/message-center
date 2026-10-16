# Priority alias contract

## Objective
Ensure confirmed QQ send readback metadata is registered against the canonical conversation external ID emitted by the adapter and returned by the Worker.

## Scope
- The device runtime command payload uses `conversation.external_id` as `externalConversationId`.
- QQ adapter events and conversation profiles use the raw `conversation-<8 hex>` alias.
- Connector and profile scope remains independently bound by the runtime and cursor key.
- No changes to device access, cloud behavior, or send confirmation rules.

- [x] Inspect runtime connector construction, Worker command construction, and adapter event identifiers.
- [x] Update the runtime alias parser and confirmed-send tests to use the raw canonical alias.
- [x] Run focused runtime tests and record the result.
