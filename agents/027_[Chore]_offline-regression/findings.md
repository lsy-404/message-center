# 验证发现

- 基线为公共 `main` 的 `b926ff0`；复用隔离 worktree，起始工作区干净。
- 根目录 Python 回归运行 71 项，通过 70 项，1 项 POSIX-only 子进程管道测试按平台跳过。
- 根目录 Node 回归运行 19 项，全部通过；Worker schema 检查和 Fluent vendor smoke 通过。
- UI 依赖使用 pnpm 本地 store 离线恢复。`vue-tsc --noEmit` 通过，Vite 构建明确使用 `safari15` 目标并成功。
- 浏览器合成 UI 覆盖渠道导航去重、实例管理及多账号过滤、技术 ID 不进入导航、双方向发言人头像/缺失头像首字占位、头像路径刷新、图片成功与失败、单独图片占位符计数、保留 literal `[图片]` 文本及 pending 附件状态；全部通过。
- Playwright 模块从 npm 本机缓存离线安装到临时目录；默认版本对应的浏览器未缓存，测试改用本机已有 Chromium 可执行文件后通过。未联网下载。
- 这不是 Safari/WebKit 或 iPad 实机 UI 验证；长期运行及锁屏行为不在本次离线测试范围。