# 调查发现

- 群备份写入使用 `INSERT OR IGNORE`，重复 external ID 之后按已存行构造规范消息，因此原有 null/旧 sender ID 会遮蔽重放中的新 sender ID。
- 群备份重复消息分支没有更新 `messages.sender_id`。
- 修复应在校验备份与规范消息均绑定同 conversation 后写入 sender 字段，避免跨会话冲突触碰旧行。

只在受控重放时更新资料，不扫描或猜测存量 ID。
