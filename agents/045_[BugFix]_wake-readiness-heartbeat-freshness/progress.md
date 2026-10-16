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

- Follow-up：`conversation_profiles.py` 在每个 JSON `ok: true` profile/avatar ACK 后调用 Relay 的30秒节流在线心跳；心跳异常不会撤销已成功上传，也不进入 connector failure backoff。无效 ACK 不报告进展。
- 新增慢批次 fake-clock 测试：20 profiles + 20 avatars，每次 ACK 模拟5秒，共200秒；确认在线心跳间隔受30秒节流且扫描/connector failure计数不变。另有无效 ACK、心跳故障与 successful sync 负控。
- Follow-up 验证：profile tests 17/17；runtime tests 90（2 skipped）；全 Python suite 126（2 skipped）；py_compile 与 `git diff --check` 通过。


## 被动实机验证

- 已安装版本：profile 模块 SHA-256 `6c7846fd1c636576311418320c70f8bf4fc8e9435fdb593d290dd93e8823dced`；runtime SHA-256 `04a01771dee3641b0ae21a5481ea54685d7c8e70fdad84f3e6ae31272cd1b390`。对应 follow-up commit `1931293`。
- 2026-10-16 01:22:03.876–01:26:46.621 UTC 连续15个被动设备样本：QQ PID 40681 稳定，source failure 最大值0；cursor有8种快照；cache 15/15保留且跨读取复用3次；cache 10,235 B、cursor 53,450 B；outbox最大值与末次值均为19。末次值不证明队列已清空。CPU单核采样16.1–44.3%，均值28.4%；ledger未变化。
- 同期10个云端样本间隔30秒。重启settle阶段最初3个为offline；经过至少90秒后，有效样本7/7均为online，最大heartbeat age 39秒，并观察到5个不同心跳。此结论按Worker 90秒 TTL计算，不把stored state直接视为fresh online；浏览器也显示QQ online。
- 观察期间无 probe、UI操作或安装；原生UI操作在观察开始前完成。该窗口约4分43秒，只支持短时被动运行证据，不是长期认证，也不能据此宣称CPU有显著改善。此前出现 `FileExistsError` 的主机harness轮次不包含设备证据，已用唯一报告文件路径纠正。
