# Progress

- 确认分支 `feature/inbox-navigation-display` 在此前本地提交之后干净，保留未跟踪 `work/`。
- 读取 `agent-mode` 工作流；查看头像重试函数、消息模板、同快照比较和现有合成浏览器夹具。
- 在 `Message` 增加可空 `senderAvatarPath`；消息旁渲染姓名首字占位和惰性异步解码头像，inbound 靠左、outbound 靠右；扩展快照比较与头像活跃缓存路径。
- 扩展 `test/ui-navigation-media.cjs`，覆盖不同头像、null头像、头像路径后到、双图片一成一败、正文literal和成功数限制；按环境变量保存合成预览。
- `pnpm run check` 与 `pnpm run build` 通过；设置 `NODE_PATH` 指向现有Playwright安装后运行定向浏览器检查通过；已生成合成 UI 预览供本地查看。
- 独立发言人头像 API 与 UI 已集成并部署验证；消息头像路径后到时会刷新对应消息。
