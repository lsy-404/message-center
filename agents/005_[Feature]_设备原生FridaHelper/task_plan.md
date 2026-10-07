# 设备原生 Frida helper 计划

- [x] 定义仅接收通用 PID、JS 输入、Frida send 结果的 CLI 协议与边界。
- [x] 实现异步连接、attach、load、结果接收、unload、detach、close 和超时取消。
- [x] 添加独立的 iOS arm64 构建 workflow，固定 devkit 版本与校验值，上传二进制、对象文件、源码与许可。
- [x] 补充文档和仓库根 `/test` 中的公开契约测试。
- [x] 运行可用的契约测试与 diff 检查。
- [x] 复核暂存范围并提交仅包含本任务的修复。
