# Findings

- The Worker intentionally suppresses `group` + `background` in `/api/connectors/events` while still returning HTTP 200. Those events must use the existing `/api/connectors/group-text-backups` route.
- Normal event acknowledgements with `suppressed > 0` are not durable acceptance; retain the outbox row and apply connector backoff. A zero-suppressed response remains idempotent and may be acknowledged.
- The group backup endpoint accepts only nonempty plain text up to 20,000 UTF-16 code units without attachments. The runtime validates these constraints before atomically committing a source cursor.
- `receiveOnly: true` registers only `receive_text` and skips command claims. Omission preserves the existing send-enabled behavior.
