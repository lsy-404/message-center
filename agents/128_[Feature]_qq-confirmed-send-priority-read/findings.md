# Findings

- `Relay.process_command` recognizes verified QQ receipts and writes the terminal command ledger result, but currently does not persist a priority-read hint.
- Scan cursor writes happen in `scan_profile` with an upsert. Send completion must re-read the current `(connector_id, profile)` row inside the same `BEGIN IMMEDIATE` transaction as the ledger update, then update only its metadata field so newer scan anchors remain intact.
- Existing receipt validation canonicalizes the source ID and validates its QQ alias/status. The new hint must reuse this validated receipt, not derive message aliases from account IDs.
- Owner source schema requires coordination with the private consumer; do not infer account identity from display labels or unrelated cache fields.

- The private consumer uses canonical owner UINs and alias FIFO order. Owner evidence is accepted only from a fully valid qfd1 directory or a qdc3 cache scoped to the exact profile; simultaneous valid sources must agree.
- The terminal QQ success path uses one immediate SQLite transaction for the ledger done update and an optional savepoint-protected latest-cursor metadata update. The cursor is re-read under that lock and updated with a value compare, preserving concurrently advanced anchors.
- Priority metadata is local only. A full cursor exceeding the existing 65,536-byte bound is left untouched; malformed optional metadata does not change the verified send outcome.
- Verification: public test suite passes 141 tests with 2 platform skips.
