# Findings

- The existing late-attachment regression exercises Worker ingestion only; it does not establish device-runtime outbox support.
- The delegated adapter contract says a delayed event keeps the same `externalId`, body, conversation, sender, time, trigger/context, and placement. It adds validated attachments and changes `contentType` from `text` to `mixed`.
- The implementation must compare normalized immutable fields and permit only the specific text-to-mixed transition, with an attachment-free old payload and nonempty validated incoming attachments.
- Preserve the original outbox sequence and queue row semantics. The source cursor and outbox mutation must stay in the existing transaction so a conflict or budget failure rolls back both.
- The normalized late event may change only `contentType` from `text` to `mixed` and add a nonempty `attachments` list. Compare all other fields using canonical JSON serialization, preserving scalar types.
- Existing `size` covers serialized event bytes plus staged attachment bytes. For enrichment, capacity must account for `new_size - old_size`, while ordinary inserts continue to consume their full size.
- An enrichment must match the original connector, profile, and external ID. Updating the row in place preserves its `seq`, so FIFO ordering and any existing outbox row identity remain stable.
- Review confirmed the existing per-page `page_ids` check already compares each normalized serialized message body by `externalId` and appends an encoded row only once. The suspected `INSERT OR IGNORE` same-batch loss is therefore unreachable in the fixed single-profile scan; no additional batch deduplicator is needed.
