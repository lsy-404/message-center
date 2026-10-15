# Findings

- Outbound messages are created with a null `messages.external_id`; command completion stores the result and delivery state only.
- Inbound event insertion uses a unique `(connector_id, external_id)` index but always assigns direction `inbound`.
- A receipt-first association can make later event insertion hit the existing outbound row. An event-first self record requires exact-ID reconciliation at completion; message text alone is not an identity key.
- The QQ event external ID is `<profile>:<shape.messageAlias>`, where `messageAlias` is `message-` plus the source's FNV-1a 32-bit hash of the canonical native source ID. The sender receipt must carry the observed alias, not substitute the raw native ID.
- D1 `batch()` executes statements sequentially in one transaction and rolls back the batch on failure, per current Cloudflare D1 documentation.
