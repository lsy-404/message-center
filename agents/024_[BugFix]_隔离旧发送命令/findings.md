# 调研结论

- `registerConnector` 当前通过单条 `INSERT ... ON CONFLICT DO UPDATE` 原子覆盖 connector capabilities；没有 send_text 从无到有的命令整理。
- Worker 命令领取仅选择 `pending` 和已过期 `leased`；回执通过 `state='leased' AND lease_token=?` CAS。把旧 lease 转入 `manual_review` 并清除 lease 字段会使迟到的旧回执失败，避免再次领取。活动 lease 可能已经 dispatch，因此需与 pending 用不同固定原因记录，但都不能自动重发。
- D1 `batch()` 顺序执行并在任一语句失败时回滚整批（官方文档：https://developers.cloudflare.com/d1/worker-api/d1-database/#batch）。因此先用旧 `capabilities_json` 的 SQL 条件栅栏隔离旧命令，再更新关联消息状态，最后更新 connector capabilities；重复注册在 capability 已含 send_text 时不再匹配栅栏。
- 旧 pending 可确认未领取；旧 leased 可能已经 dispatch，需保留其消息与 payload 并标待确认。计划保留所有内容，将 command 设为 `manual_review`，消息设为同语义状态；原因码分别说明“启用发送前的旧待发命令”与“启用发送前已有 lease”。
- 新 connector 的注册不会匹配旧 connector 状态子查询，故不会隔离不存在旧 connector 的命令。
