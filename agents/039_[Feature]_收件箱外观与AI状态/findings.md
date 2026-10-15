# 调查结果

- 改版前截图：接入管理卡片的“查看此账号会话”按钮继承 `.quiet-button` 的 34px 固定宽度，文字被压成竖排。
- 时间、元信息与能力标签大量使用 9–10px 字号，在 iPad 上难以扫读；头像、渠道入口均为同一灰色，跨渠道“全部”视图无法区分来源。
- ⚙ ↪ ↻ ▤ ◆ ▱ □ 等 Unicode 字符作为图标，iPad Safari 可能渲染为 emoji 或缺字；折叠标记 ▱ 在 Chromium 中只显示为短横。
- Fluent 样式表以零特异性规则给所有原生 `button` 加控件底色和 1px 阴影，列表项需显式取消，否则每行下方出现分隔线。
- Agent 回复以 `created_by = agent:<consumerId>`、发送者名 “Agent” 入库，网页此前与本人发送无法区分；所有 immediate 入站消息都会进入 `agent_queue`，其 `state`（pending / leased / completed / dead_letter）能直接说明 AI 是否已接手或转人工，但 inbox 未返回。
- `agent_queue.message_id` 为主键，消息详情查询追加 LEFT JOIN 不会改变行数或排序。
- iPad mini 4 横屏为 1024px，原 1000px 断点不生效，线程头部在三栏下过窄；断点调整为 1100px。
- 用户反馈：AI 状态只需标注是否已读。`agent_queue` 中 `pending` 表示尚未被领取，其余状态都意味着 Agent 已读取过该消息。
- 富内容没有结构化字段：公开适配器把原生元素压平成行首标签（`[卡片] 标题 · 摘要 · 来源`、`[转账]`、`[拍一拍]`、`[picture:…]`、未知元素 `[kind:type-N]`），会话摘要来自原生客户端（`[小程序]…`、`[QQ小程序]…`）。私有适配器的实际引用格式不在仓库内，因此渲染层同时接受 `[引用]`、`[reply:type-7]` 与微信复制格式 `「作者：内容」` + 虚线；改变已入库正文格式会触发 Worker 的同 ID 正文冲突，所以不修改适配器输出。
