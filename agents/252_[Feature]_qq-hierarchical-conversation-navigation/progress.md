# Progress

- Read the `agent-mode` skill, repository project index, task index, and `agents/local.instructions.md`.
- Inspected public main `bca312c`, current App.vue group-assistant state/sidebar/list, conversation-list helpers, and `/api/inbox` placement/type fields.
- Confirmed that the existing data contract supports group-assistant membership but does not contain real nested folder-parent metadata.
- Created an isolated worktree from the reviewed main; no device, cloud, or send operation was performed.
- Replaced the standalone 群助手 sidebar/view with one folder row in the QQ root list; opening it presents the matching QQ groups directly.
- Added bounded path and breadcrumb helpers, scoped filtering/counts/selection behavior, and kept ordinary all-channel inbox rows flat.
- Replaced the old parallel-view tests with focused path, membership, filter, selection, and level-bound tests under `/test`.
- Installed only the UI lockfile dependencies in this worktree; `node --test test/qq-group-helper.test.mjs`, `pnpm run check`, and `pnpm run build` pass.
