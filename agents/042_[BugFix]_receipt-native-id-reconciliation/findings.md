# Findings

- Outbound messages are created with a null `messages.external_id`; command completion stores the result and delivery state only.
- Inbound event insertion uses a unique `(connector_id, external_id)` index but always assigns direction `inbound`.
- A receipt-first association can make later event insertion hit the existing outbound row. An event-first self record requires exact-ID reconciliation at completion; message text alone is not an identity key.
- `messageAlias` is a 32-bit FNV-derived metadata alias and can collide for different native source IDs (`2328622970` and `2948735191` both produce `message-e37f9132`). It is not a safe message identity. QQ event and send external IDs now use `<profile>:qq-message:<canonical native sourceId>`; the receipt alias remains independently checked against its source ID.
- D1 `batch()` executes statements sequentially in one transaction and rolls back the batch on failure, per current Cloudflare D1 documentation.
- A self event can arrive after the completion pre-read and before the fenced batch. If the batch hits the unique external-ID index, the Worker performs one bounded exact-event re-read and retries reconciliation once; the original completion batch rolls back atomically and no device send is repeated.
