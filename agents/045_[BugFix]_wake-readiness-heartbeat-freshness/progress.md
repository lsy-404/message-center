# 进度

- 在 `device_runtime.py` 加入每 connector 的最近成功心跳状态/时间和固定30秒同状态节流；状态变化立即尝试发送，失败仍走已有独立退避。
- 每个真实 outbox ACK 后尝试在线心跳；同状态节流限制快速 ACK，不改变 source health、扫描时间、游标或命令 gate。
- scan eligibility 和 scan 后心跳/命令门禁改用现有 `ensure_active()`；TTL过期时按原节流和adapter契约重新读取 readiness，失败保持 fail closed。
- 新增慢ACK、状态切换节流、慢扫描+profile/avatar同步后的 fresh ready、慢扫描后的 fresh not-ready 测试；调整同状态周期心跳测试预期。
- `python test/test_device_runtime.py`：88 tests通过、2平台跳过。
- `python -m unittest discover -s test -p 'test_*.py'`：121 tests通过、2平台跳过。
- `py_compile` 与 `git diff --check` 通过。
- `node --test test/*.test.mjs` 未全通过：新 worktree未安装 `openid-client`，12个依赖该包的测试启动失败；31个其他用例通过。该 runtime 改动不触及 Worker/Node代码。
- 未访问设备或云端，也未部署。
