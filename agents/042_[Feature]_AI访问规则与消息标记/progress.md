# 进度

- 新增 `cloudflare-worker/migrations/0010_agent_access_and_read_marks.sql` 并同步 `worker/schema.sql`；迁移测试断言新列。
- 新增 `cloudflare-worker/worker/agent-access.js`；`worker/index.js` 在入队、listen/claim、reply、文件列举与下载处按解析结果判断，claim 返回 `scope.access`、`scope.commandAuthority`、`sender.commandAuthority`、`marks`、`markNames`。
- 新增管理员接口 `GET/PUT /api/connectors/<id>/agent-settings`、`GET/PUT /api/conversations/<id>/agent-settings`、`POST /api/conversations/<id>/read`；MCP 新增 `list_conversations`、`read_messages`。
- UI 新增 `AgentRulesDialog.vue`、`agent-rules.mjs`、`http.ts`；消息状态行显示标记标签与 `#数字`，会话头部显示规则摘要按钮，接入卡片显示可编辑的默认规则表。
- 新增 `test/agent-access.test.mjs`、`test/worker-agent-access.test.mjs`、`test/ui-agent-rules.test.mjs`；替换上一任务的 `worker-inbox-agent-activity` 测试；更新 Playwright、smoke 与 schema 测试。
- `pnpm run check`、`pnpm run build`、`node --check`、`node --test test/*.test.mjs`（108 项）与 `test/ui-navigation-media.cjs` 通过；截图基于合成数据，Safari/iPad 实机与生产 D1 迁移未验证。
