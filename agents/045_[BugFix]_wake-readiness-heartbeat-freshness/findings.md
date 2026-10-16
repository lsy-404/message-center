# Findings

- `pass_once()` 在每轮最多调用五次 `flush_one()` 后才进入 scan 和 heartbeat。即使收到 ACK，慢附件上传也可能让 Worker 的 90 秒 heartbeat 窗口在下一个 heartbeat 前过期。
- `ensure_active()` 的 readiness 有效期为 60 秒；`pass_once()` 在长 scan/profile sync 后只读取缓存 TTL，不会主动刷新 readiness。过期缓存可使成功读取被报 offline，也会关闭后续 command polling。
- ACK 只允许用于对应 connector 的 online heartbeat；它不改变 source health、新鲜扫描时间、游标或 command polling gate。相同状态的成功心跳固定间隔30秒节流，状态切换不受该间隔阻挡；失败仍服从既有心跳退避。profile 与 sender-avatar 各自只有在 JSON `ok: true` ACK 校验后才报告进展。
- 修复保持上传/ACK与 outbox 删除顺序、游标提交、失败退避及 `process_command` 幂等账本语义不变。所有新测试使用假时钟和本地 HTTP/adapter替身。
- Python根测试全部通过；Node测试集合在此新worktree因未安装 `openid-client` 有12个测试启动失败，31个其他用例通过。相关改动仅涉及 Python runtime 与其测试。
- 本任务只改公开 runtime，不访问设备、云端或部署。
