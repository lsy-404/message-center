---
description: Always Load
applyTo: '**'
---
# 项目规则
- 不依赖电脑常驻中继，不假设 iPad 通过 USB 或局域网连接电脑。
- 针对 iPad mini 4 限制并发、重复历史读取和失败重试；真实运行验证与静态验证明确区分。
- 云 UI 以 @platform-kit/fluent 包为主要视觉主题。
- 不发布私有适配器、密钥、设备标识、联系人或消息内容。
- 所有新增测试放仓库根目录 test。
- 子任务用隔离 worktree 提交，再本地合并 main；不包含旧目录未提交改动。
