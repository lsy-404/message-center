# Findings

- 公开运行器对每个 `(connector_id, profile)` 保存一个 opaque cursor；每个 scan 页的 events 和 cursor 在同一 SQLite 事务提交，因此可用 profile cursor 包含每会话状态。
- 初始 baseline 必须显式选定；此状态机采用“不回填首次观察 head 以前的消息”，首次扫描只记录当前 head。
- 安全增量读取采用冻结 sweep head：开始时捕获目标 head，后续只沿旧方向读取不晚于目标 head 的页；每页最多 20 条。单页 events 与 next cursor 一起由运行器原子入 outbox。到达旧 committed head 后才提交冻结 head；扫描期间新到消息留给后续 sweep。
- 通用代码只能约束适配器返回页的协议与状态迁移，不能证明原生 API 的 anchor 是稳定、独占且按顺序向旧分页。QQ/微信的实机覆盖证明仍需私有适配器验证；不完整、乱序、无进展和越界页应失败且不得推进 cursor。
- continuation `before` 按 inclusive 模式返回时必须是该页首项，状态机只剔除这一项。未完成页必须显式给出 `has_more=true`；不能从消息数不足预算推断源已到开头。空 baseline 时只有 source 明确报告 `reached_beginning=true` 才能完成 sweep。
- 每 profile cursor限制为200个会话、每个native ID最多256字符、JSON序列化后最多64KiB；状态机按每次最多20条验证，事件bytes预算仍由现有runtime复核。
- 现有 TS 映射的稳定 Worker externalId 为 `profile.id:messageAlias`，消息事件去重还受 connector ID 作用域约束。本次公共状态机不生成或更改消息标识。
