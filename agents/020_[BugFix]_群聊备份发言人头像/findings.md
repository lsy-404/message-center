# 调查发现

- 私有 QQ 的头像候选与消息事件使用同一 sender alias；此处未发现身份字段错配。
- `/api/inbox` 已按 `(connector_id, sender_id)` 连接 `sender_avatars` 并返回 `senderAvatarPath`。
- `/api/group-text-backups` GET 只连接 `conversation_profiles`，其响应没有 `senderAvatarPath`。这是已确认的读取接口缺口；当前主 UI 使用 `/api/inbox`，所以该缺口单独不能证明 inbox 中 QQ 头像缺失的原因。

不记录任何设备、账号或消息数据。
