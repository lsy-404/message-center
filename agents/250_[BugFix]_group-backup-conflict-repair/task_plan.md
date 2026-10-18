# Group backup conflict repair

- [x] Create an isolated worktree from the reviewed public main and load repository rules.
- [x] Identify every `message_external_id_conflict` branch in group-backup and ordinary event ingestion.
- [x] Compare the observed 400 branch against root's read-only D1 evidence before choosing a repair.
- [x] Implement only the proven attachment-enrichment case while preserving message identity boundaries.
- [x] Add `/test` regression coverage for the reachable repair and strict negative cases.
- [x] Run focused Worker tests, review the diff for scope/secrets, and commit locally without deployment.
