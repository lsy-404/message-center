# 进度

- 已确认当前 worktree 干净，并从 `main` 建立任务分支。
- 已检查私有 sender ID 映射、Worker inbox JOIN、群备份 GET 投影；未编辑私有文件。
- 已给群备份 GET 增加按 connector/sender 关联的头像路径投影。
- 合成回归覆盖双 connector 隔离、存在头像与缺失头像；`node --test test/worker-sender-avatars.test.mjs` 通过。
- Worker 定向套件 `node --test test/worker-*.test.mjs` 通过（4 项）。
- 仍需提交并向主任务报告：当前 UI 读取 `/api/inbox`，本修复针对另一个读取端点，不证明已知 inbox 抽样现象已解决。
