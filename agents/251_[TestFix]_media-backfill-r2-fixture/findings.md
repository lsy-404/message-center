# Findings

- The standalone media-backfill test omitted the `FixedLengthStream` global used by the production inbound-upload path. Loading the schema test first masked that setup error but did not repair the media test's R2 mock.
- The media test's `put()` returned only `{ size }`, while production verifies both uploaded size and SHA-256 checksum from R2 metadata. This caused `uploaded_file_integrity_mismatch` in the backfill path.
- The fixture now enforces exact stream length and returns the checksum as an `ArrayBuffer` from `put`, `head`, and `get`, matching the mature schema fixture's R2 contract. Production code and all existing integrity, avatar, direct attachment, group attachment, and conflict assertions remain unchanged.
