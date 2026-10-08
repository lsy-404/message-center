# 进度

- Worker 注册先按旧 capabilities 栅栏隔离 `pending` 与 `leased`，保留命令 payload，设置固定人工审核原因并清除旧 lease。
- 关联出站消息和附件进入 `manual_review`；pending 原因标明 `dispatched: false`，leased 原因标明结果可能不确定。
- 隔离、消息/附件状态、条件审计事件和 capabilities upsert 在一个有序 D1 batch 内，失败会回滚整个变更。
- 新增真实 SQLite 测试覆盖 pending/过期及活动 lease、重复并行注册、新命令不被隔离、初次启用、未启用发送及事务回滚。
- `node --test test/*.test.mjs`：17 项通过；`node cloudflare-worker/worker/schema-test.mjs`：通过。
- 未合并、推送或部署；root 接手后续集成。
