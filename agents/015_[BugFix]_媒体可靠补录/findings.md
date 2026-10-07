# Findings

- 根因：多个 connector 共享同一个媒体目录，stagingKey 无全局命名空间。
- 根因：Worker 对普通重复消息沿用旧附件元数据；群聊重复备份拒绝附件列表扩展。
- 限制：新媒体补录必须与原消息 externalId、conversation 和 body 一致，且文件已由 connector 上传并校验元数据；已有附件不可被删除或重绑。

## 实现约束
- staging 根目录下按已配置 connector ID 建 0700 子目录；适配器每次 scan 只得到当前 connector 子目录。清理按 connector 的 outbox 引用独立执行。
- 启动时把旧 flat root 中被 outbox 引用的文件迁入对应子目录，并清理旧 flat root 的未引用普通文件，保持已有持久队列可重试。
- 新增附件必须先上传并与 D1 中的 connector、会话、文件名、MIME、大小、hash 一致；既有文件只能仍绑定原 message。
- 普通重复事件与群聊备份合并最多 20 个附件；正文或同文件 ID 元数据冲突返回错误。普通 background -> immediate promotion 保留原有语义例外。
- 附件补录只更新消息附件 metadata/content type 并依赖现有 `INSERT OR IGNORE agent_queue`，不新建消息或增加 unread。

## 验证记录
- `python -m unittest discover -s test`：46 tests passed, 1 skipped。
- 所有根 `test/*.mjs` 直接运行通过，包括新增 Worker media backfill 和大群 inbox 测试。
- `node cloudflare-worker/worker/schema-test.mjs` 通过。
- `git diff --check` 通过。
- `pnpm --dir cloudflare-worker/ui check/build` 未运行成功：该 worktree 没有 UI `node_modules`；本次未修改 UI。
- 首次 Worker fixture 误用不存在的 `DatabaseSync.transaction()`，改为逐条执行 stub statements 后通过。Schema test 暴露旧 promotion fixture 正常依赖 background 文本提升，保留该既有路径，同时只对非 background 重复消息拒绝正文冲突。
