# 进度

- 新增 `ui/src/icons.ts`（Fluent UI System Icons 1.1.344，MIT，与 Fluent 包 NOTICE 同源）与 `AppIcon.vue`，替换全部字符图标。
- 新增 `ui/src/presentation.mjs`：稳定色调、中文相对时间、日期标签、线程日期分隔与 5 分钟内同一发送者合并；`conversation-list.mjs` 增加 `unreadOnly`。
- `App.vue`：导航显示未读数与接入在线比例；会话行显示渠道色标、群聊/折叠/置顶图标、未读加粗；线程显示日期分隔、AI 代发标识、发送状态与 AI 队列状态及头部概况；接入管理按接收/发送分组能力并显示最近活动；修复竖排按钮。
- 机器可读：会话行与消息带 `data-conversation-id`、`data-unread-count`、`data-author-role`、`data-delivery-state`、`data-agent-state`，时间使用 `<time datetime>`，消息区为 `role="log"`。
- Worker `readInbox` 消息新增 `authorRole`（contact / owner / agent）与 `agentState`；不返回 `created_by` 原值。
- 新增 `test/ui-presentation.test.mjs`、`test/worker-inbox-agent-activity.test.mjs`（未改 Worker 时失败、改后通过）；扩展 `test/ui-navigation-media.cjs` 覆盖 AI 代发、队列状态、未读筛选与时间戳。
- `pnpm run check`、`pnpm run build`（Safari 15 目标）、`node --check worker/index.js`、`node --test test/*.test.mjs`（88 项）与 `test/ui-navigation-media.cjs` 通过。
- 截图验证基于合成 fixture 与 Chromium（桌面浅/深色、768×1024、1024×768），Safari/iPad 实机未验证；未部署、未操作设备。
- 反馈修订：`agentState` 改为 `agentRead`，页面只显示“AI 已读 / AI 未读”及头部未读数；新增 `ui/src/rich-body.mjs` 把正文解析为引用、卡片、金额、提示与媒体块，单独的卡片/转账去掉外层气泡，拍一拍居中显示；会话列表摘要使用同一规则。新增 `test/ui-rich-body.test.mjs`，更新 Worker 与 Playwright 测试。
