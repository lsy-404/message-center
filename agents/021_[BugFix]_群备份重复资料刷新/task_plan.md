# 任务计划

在群备份重复摄取时，仅对相同 connector、external ID 和 conversation 的消息刷新有效且非空的 sender ID/name。保留正文、时间和附件；无 sender ID 时保留已存 sender 字段；跨 conversation 冲突继续失败。用 Worker + SQLite 合成测试覆盖旧 null、旧 alias、无 sender、冲突和重复消息计数。实现与验证已完成。

边界：不迁移或批量回写历史数据；不操作云端或设备。
