# Task 032: Native media outbox enrichment

## Goal
Allow a delayed attachment payload to enrich an existing attachment-free outbox row when it represents the same immutable native event.

## Constraints
- Only same connector/profile/external ID and same event body and immutable metadata may qualify.
- Existing attachments must be absent or empty; incoming attachments must pass the existing validation path and be nonempty.
- Preserve the stored event identity, ordering, staged-media metadata, and queue accounting; reject every other difference.
- Keep the update atomic with source cursor commit and outbox byte-budget enforcement.
- Tests stay under repository-root `/test`; no cloud/device operations.

## Steps
- [x] Inspect event serialization, existing conflict behavior, validation and transaction boundaries.
- [x] Implement the narrow attachment-only enrichment and rollback-safe budget handling.
- [x] Add meaningful tests for successful enrichment, exact conflict rejection, invalid media, budget, and cursor rollback.
- [x] Run required repository checks, review diff, and commit the isolated branch.
