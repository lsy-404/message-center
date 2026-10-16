# 任务计划

- [x] 固定现有 ACK 心跳、readiness TTL、scan health 与 command gate 的边界。
- [x] 复用集中式心跳发送逻辑，加入30秒同状态成功心跳节流与 ACK 后在线进展心跳。
- [x] 在扫描开始与扫描/资料同步结束后刷新真实 readiness。
- [x] 在 profile/avatar 的每个有效 ACK 后汇报有界上传进展，失败或无效 ACK 不产生进展心跳。
- [x] 为慢 ACK、慢 scan/profile sync 和 fresh readiness 失败添加 fake-clock 回归测试。
- [x] 运行 runtime 与根 Python 测试、自检差异；Node 全套测试因 worktree 缺少 `openid-client` 依赖未能运行。
- [x] 提交隔离分支并交 root 审查。
- [x] Follow-up：每个有效 profile/avatar ACK 后触发现有节流心跳；无效 ACK 不触发。
