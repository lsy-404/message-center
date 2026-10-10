# Progress

- Loaded the agent-mode workflow and public project instructions.
- Created an isolated worktree from the verified public main branch; no code changes yet.
- Updated `bridge/device-runtime/device_runtime.py` so an existing same-profile event ID accepts only the exact text-placeholder to mixed-with-attachments transition, with all other JSON fields equal. Existing row updates use the precise prior sequence/body/size predicate inside the cursor transaction.
- Queue capacity now includes only the enrichment size delta; on overflow, the transaction rolls back and the source cursor remains unchanged.
- Added tests for successful same-row enrichment, immutable-field/content-type conflicts, invalid staged files, byte-budget rejection, and cursor-update failure rollback.
- Full repository Python suite after all changes: 85 tests passed, 1 platform-specific skip. The focused device-runtime module passed 52 tests with 1 platform-specific skip.
- Follow-up review added an explicit encoded-batch deduplicator before capacity accounting: exact same-profile event rows count once; same-ID differences and same-batch placeholder-to-enrichment transitions fail closed. Added regressions for changed-body cursor rollback and exact duplicate budget usage.
