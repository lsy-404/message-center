# 操作记录

- 2026-10-07：检查并复用已有 fluent-ui worktree；保留未跟踪的 `work/` 截图，基于 `main` / `54db341` 新建隔离分支。
- 2026-10-07：读取 Frida 16.3.3 iOS arm64 devkit 示例与 C API 头文件；确认远端设备连接、attach、脚本创建/load/unload、detach 与 manager close 均有异步接口。记录 devkit SHA-256：`C31AA39618A6996BF43A472F2F48E3E4C2CC72EEE101A1ED6820192CBF58BDEC`。
- 2026-10-07：新增 Objective-C CLI、手动/窄路径 workflow、使用文档与根 `/test` 合约测试。当前 Windows 主机没有 iOS SDK/编译器，尚未执行 iOS 原生构建或设备运行。
- 2026-10-07：`node --test test/device-native-helper-contract.test.mjs` 初次通过（4 项），`git diff --check` 通过；原生编译检查留给 macOS workflow。
- 2026-10-07：修复 load 回调返回前多次 `send` 的覆盖/泄漏风险；将首个有效结果锁存，并为 JSON 外层预留预算，超大最终输出改为稳定错误 JSON。
- 2026-10-07：复核 workflow 使用 macOS runner 的 iPhoneOS SDK、arm64/iOS 15.0 target、devkit SHA 校验与 Frida 示例链接依赖，并仅上传临时 artifact；当前机没有 Apple 工具链，未运行原生构建。
- 2026-10-07：加入首个有效结果锁存与 envelope 边界回归检查；最终 `node --test test/device-native-helper-contract.test.mjs` 通过 5 项，`git diff --check` 通过。
