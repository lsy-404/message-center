# Findings

- The existing TypeScript unified relay depends on Node filesystem/process APIs and cannot run in the target iPad environment.
- Worker event ingestion deduplicates by connector ID and stable external ID; a lost HTTP response is safe to retry with the same event ID.
- Worker command polling accepts `limit=1`; its lease lasts 15 minutes and completion is fenced by the current lease token.
- Device source cursors must be committed in the same local transaction as durable outbox inserts. Backpressure must fail before calling the adapter so the cursor cannot skip messages.
- Physical sends cannot be made exactly-once across process death. Persist `started` before invoking the private adapter, and turn a replayed started record into `uncertain` without invoking again.
- Private adapter contract: executable receives one JSON object on stdin and emits one JSON object on stdout. `scan` input includes profile, opaque cursor, page limit, and history mode; output is `{ok:true, cursor:<opaque>, messages:[<normalized Worker event>], health:"online"}`. `send` input includes profile, command ID, idempotency key, conversation external ID, text or attachment metadata; output is `{ok:true, receipt:<string>}` or `{ok:false, retryable:<bool>, error:<short code>}`. No vendor-specific adapter implementation belongs in this public repository.
- No claim of live iPad compatibility until Python 3.9.9 and the private adapter are confirmed on-device.
