# 调查发现

- App.vue 的会话详情和群聊页面共用 `/api/inbox?conversationId=...`，通过 Worker `readInbox` 的 `messages` 查询加载；前端不调用 `/api/group-text-backups`。
- Worker 将附件 ID/MIME/可下载状态随 inbox JSON 返回，图片元素通过 `/api/files/:id` 加载；头像使用独立 `/api/avatars/:connector/:conversation` 路由。
- 脱敏 GET 诊断显示 4 个会话详情失败（含 3 个群聊），错误均为 `D1_ERROR: too many SQL variables`。`readInbox` 先限制最多 300 条消息，再将全部 ID 展开为 attachments 查询占位符；超过 D1 的变量上限即失败。
- 修复将附件查询改为按 conversation_id 子查询最近 300 条消息，单个绑定参数；根测试用 125 条消息并强制 D1 mock 拒绝超过 100 个绑定参数，验证详情及附件返回。
- Worker inbox JSON 已声明 UTF-8，脱敏原始字节也是有效 UTF-8；响应中已有 U+FFFD（9 个会话标题损坏），而成功详情的正文和发送者无此字符。已落库的 replacement character 无法由 UI 无损还原，需在数据产生/写入端处理。
- 实际诊断附件数为 0，当前缺图源自旧采集管线未上传附件，UI 无法显示缺失的对象。另将 PNG/JPEG/GIF/WebP 下载响应改成 inline，其他文件保留 attachment；行为测试覆盖这两类响应。
- 本任务修复了已证实的群聊 GET 参数上限问题以及已有栅格图像的 inline 响应问题；数据中已持久化的 U+FFFD 和采集端未上传的附件不能由云 UI/GET 层恢复。
