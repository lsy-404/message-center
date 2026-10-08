# 018 发言人头像同步

## Scope
Add a dedicated connector-scoped sender avatar store and authenticated upload/download routes. Add bounded private-data-free public runtime synchronization before cursor/outbox commit. Return avatar URLs in the existing inbox message query without adding per-message queries. Do not change UI, private adapters, migrations, or live environments.

## Plan
- [x] Verify current branch/worktree is clean and create an isolated sender-avatar branch based on the completed profile-avatar work.
- [x] Load agent-mode, Cloudflare, and Workers best-practice instructions; inspect existing Worker avatar route, inbox SQL, schema, runtime transaction, and tests.
- [x] Retrieve current official Cloudflare Worker, D1, and R2 references relevant to request handling, SQL, object writes/deletes, and `waitUntil`.
- [x] Add the dedicated sender avatar table and authenticated connector upload/session-authenticated download routes, including bounded image validation, idempotent object reuse, upsert, and superseded-object cleanup.
- [x] Add one-query inbox sender avatar URL selection for the existing 300-message page.
- [x] Add strict, bounded `sync_sender_avatars` and invoke it before scan cursor/outbox transaction.
- [x] Add root tests for route auth/isolation/hash/size/inbox and runtime sync failure cursor rollback.
- [x] Run targeted and appropriate full suites, review diff, force-add this task's audit files, and commit locally.
