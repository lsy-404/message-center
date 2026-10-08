# 任务计划

- [x] 读取项目规范、接收只读审计与 Worker 命令状态迁移。
- [x] 审查 D1 batch 顺序、事务回滚和 connector capability CAS 条件，并将隔离方案交 root 审核。
- [x] 在 registerConnector 中将旧 pending/leased 命令隔离、关联消息标记待确认，再启用 send_text，放入同一 D1 batch。
- [x] 添加真实 SQLite Worker 测试：首次启用、重复启用、新命令保留、pending/lease 分类、有效旧手工审核不变和失败回滚。
- [x] 运行根测试与 worker schema test，检查差异，更新审计并本地提交；不合并、不推送、不部署。
