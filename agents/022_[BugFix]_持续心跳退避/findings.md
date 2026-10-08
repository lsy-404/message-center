# 调查发现

- `Relay.pass_once()` 在 scan 失败后调用共享 `failed()`，然后 heartbeat 受相同 `eligible()` gate 阻止；共享退避最长 300 秒，Worker 90 秒未收心跳会显示离线且 `lastSeenAt` 停滞。
- register、flush、command、scan 也共用 connector 级退避，因此任一失败都能暂停心跳。
- 真实 `pass_once()` 诊断确认：两端注册成功；QQ scan 与 heartbeat 成功；微信 scan 抛异常后被 pass 捕获，共享退避生效，微信 heartbeat 未调用。
- Worker heartbeat 接口每次成功都写 `last_seen_at`，且可接收 `status`；register 冲突更新不清除该时间。
- 修复采用独立 heartbeat 退避，指数间隔 15、30、60 秒封顶。心跳按本 connector 的扫描新鲜度报告 online/offline，不重置业务操作退避。
- 心跳仍在串行 `pass_once()` 的操作边界发送，不在原生 scan/send 子进程等待时并发发送；60/90 秒长操作可能造成短时 freshness 边界，单独作为限制保留。
