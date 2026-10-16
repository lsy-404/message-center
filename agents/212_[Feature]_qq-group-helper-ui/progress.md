# 执行记录

- 确认目标隔离 worktree 基于 `origin/main` 干净基线 `3caeb95e4885860799afa491782a5aa86a814115`。
- 改动 `cloudflare-worker/ui/src/conversation-list.mjs` 与 `.d.mts`：新增严格 QQ 助手分类 helper，并为过滤增加 connectorKind 条件。
- 改动 `cloudflare-worker/ui/src/App.vue`：QQ 协议筛选、群助手导航数量/未读、复用搜索/未读/分页的助手列表、QQ 总列表返回按钮和现有选择流程。
- 新增 `test/qq-group-helper.test.mjs`：覆盖 folded/message_box 纳入、normal/direct/其他协议/unknown 排除、搜索/未读组合和自定义 display label。
- `pnpm check` 与 `pnpm build` 在 `cloudflare-worker/ui` 通过；`node --test test/qq-group-helper.test.mjs test/channel-labels.test.mjs test/inbox-conversation-capacity.test.mjs` 9 项通过。
- `git diff --check` 通过；尚未提交。
