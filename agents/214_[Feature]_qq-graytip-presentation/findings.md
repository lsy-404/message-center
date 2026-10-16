# Findings

- Public event ingestion reaches `ingestEvents` through `bridge/src/unified-relay.ts`; `IncomingBridgeMessage` is persisted by the spool adapter, parsed by a Zod schema, normalized into the Worker event payload, and then stored in message `metadata_json`.
- The Worker knows the authenticated connector kind from its database row. The marker can be accepted only when that kind is exactly `qq`, the event explicitly declares `isSelf: false`, the event is text-only with no attachments, and the presentation literal is exactly `system`.
- Inbox message response currently omits metadata. It can project the marker only from validated stored metadata and only for inbound QQ rows without attachments.
- System events must not be added to the agent queue; this keeps gray tips visible to users without turning them into prompts.
- Historical upgrades must be limited to the exact old body `[类型:8]` and a conditional update of the same existing inbound row. Sender/avatar/time/receipt identity are preserved.
- Current Cloudflare docs confirm D1 batch statements are sequential transactional operations; this change can use the existing prepared UPDATE semantics without a new schema or migration.
- The duplicate upgrade also checks `attachments` rows directly; checking only `metadata_json.attachments` could miss a linked file when legacy metadata is incomplete.
- The conditional upgrade compares the exact previously-read `metadata_json`; attachment metadata added between placeholder inspection and UPDATE therefore loses the compare-and-swap and is rejected by the existing conflict re-read.
- The active iPad runtime carries the explicit marker only for QQ inbound records and routes it through normal event ingest. Reply authorization also excludes rows already leased before a placeholder upgrade and rechecks the source row atomically when inserting the reply command.
- The existing agent queue may already contain a placeholder. The message marker is excluded from listener, claim-by-ID, and next-message queries; the row stays pending rather than being consumed as an agent prompt.
- The UI fixture's system notice includes a visually hidden timestamp. Its assertion checks the direct text node and computed centering, not the full paragraph `textContent`.
- The synthetic browser runner required a temporary Playwright install because this checkout had no browser test dependency. Edge was provided through the existing `CHROMIUM_EXECUTABLE_PATH` hook; no project dependency was added.
