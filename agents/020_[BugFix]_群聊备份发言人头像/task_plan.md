# 任务计划

修复 `/api/group-text-backups` GET 只返回会话头像、不返回发言人头像的问题。按 connector 与 sender ID 左连接 `sender_avatars`，为存在头像的行生成现有 sender-avatar GET 路径。用 Worker 合成测试覆盖有头像和无头像的行，并运行定向测试及公共 Worker 测试。已完成代码和验证。

边界：不修改私有适配器、UI、设备或云端部署；不改 schema。
