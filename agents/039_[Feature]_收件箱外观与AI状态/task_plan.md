# 任务计划

## 目标
优化云端收件箱外观：本人能更快扫读未读、渠道与 AI 代理状态；浏览器中的 AI agent 能从语义结构读取同样信息。

## 约束
- 继续以 @platform-kit/fluent 为主题；Safari 15 / iPad mini 4（768×1024 与 1024×768）可用，不依赖 color-mix。
- 不在会话行或消息详情写入接入实例名称；不在 UI 暴露 trustTier 或 Agent consumer ID。
- Worker 只做只读字段补充，不改变队列、发送或授权语义；不部署、不操作设备。

## 计划
- [x] 用合成 fixture 截取改版前桌面、iPad、深色与接入管理页面，记录问题。
- [x] 用 Fluent UI System Icons 内联 SVG 替换 Unicode 字符图标。
- [x] 会话列表：渠道色标、名称色调头像、未读强调、相对时间、“全部/未读”切换。
- [x] 消息线程：日期分隔、同一发送者连续消息合并、发送/AI 状态标签、AI 代发样式与头部概况。
- [x] inbox 消息返回 `authorRole` 与 `agentState`；补充 Worker、纯函数与 Playwright 测试。
- [x] 语义与机器可读：landmark、aria-current/aria-pressed、`<time datetime>`、`data-*` 属性。
- [x] 运行类型检查、构建、全部 Node 测试与页面测试，更新文档。

## 反馈修订
- [x] AI 状态只标注“AI 已读 / AI 未读”，不显示处理、待处理或转人工；inbox 改为返回 `agentRead`。
- [x] 渲染 QQ/微信引用、小程序、链接、卡片、转账、红包、拍一拍与媒体占位，会话列表摘要同步压缩。
