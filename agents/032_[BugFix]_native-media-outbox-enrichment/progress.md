# Progress

- Loaded the agent-mode workflow and public project instructions.
- Created an isolated worktree from the verified public main branch; no code changes yet.
- Updated `bridge/device-runtime/device_runtime.py` so an existing same-profile event ID accepts only the exact text-placeholder to mixed-with-attachments transition, with all other JSON fields equal. Existing row updates use the precise prior sequence/body/size predicate inside the cursor transaction.
- Queue capacity now includes only the enrichment size delta; on overflow, the transaction rolls back and the source cursor remains unchanged.
- Added tests for successful same-row enrichment, immutable-field/content-type conflicts, invalid staged files, byte-budget rejection, and cursor-update failure rollback.
- Full repository Python suite after all changes: 85 tests passed, 1 platform-specific skip. The focused device-runtime module passed 52 tests with 1 platform-specific skip.
- Follow-up review corrected the suspected same-batch regression: per-page `page_ids` already rejects a different normalized body for the same external ID and encodes exact duplicates once. Removed the redundant encoded-batch helper; retained end-to-end tests for changed-body cursor rollback and exact-duplicate budget usage.
