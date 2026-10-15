# 任务计划

## 目标
为收发消息加内部数字标记（AI 发送 / 人发送 / 人已读 / AI 已读 / 发送人无指令权限），并按会话与接入两级提供 AI 访问规则：是否可见、是否主动推送处理、是否接受指令、发送人是否有指令权限、AI 是否可回复。

## 默认规则（用户指定）
- 私聊：可见，主动推送处理，可回复，不接受指令。
- 群聊（不在群助手中）：可见，仅@或关键词提及时推送处理，可回复，不接受指令。
- 群助手中的群聊：可见，不推送处理，不回复，不接受指令。

## 约束
- 标记只在 Message Center 内部，不发往外部渠道。
- 普通群聊文本仍不进入即时队列；关键词沿用设备适配器的提及词判定。
- 旧版 trusted 策略的会话保持指令语义；项目与动作范围仍只来自服务端策略。
- 不部署、不操作设备；新增 migration 由部署流程按序应用。

## 计划
- [x] migration 0010：会话/接入 `agent_settings_json`，消息 `owner_read_at` / `agent_read_at`；同步 schema.sql 与迁移测试。
- [x] `worker/agent-access.js`：内置默认、接入与会话覆盖、旧策略映射、指令权限与标记位。
- [x] Worker：入队、listen/claim、回复、文件读取按规则判断；claim 与 read 记录 AI 已读；inbox 返回 marks、commandAuthority、agentAccess 与接入默认。
- [x] 接口：会话与接入 agent-settings、会话 read；MCP `list_conversations`、`read_messages`。
- [x] UI：消息标记标签与数字、会话显示时记录人已读、会话“AI 规则”对话框（含指令发送人）、接入卡片默认规则表、不可见会话图标。
- [x] 测试与文档。
