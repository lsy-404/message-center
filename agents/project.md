# Message Center
> 最后更新：2026-10-07

## 项目目标
设备主动通过 HTTPS 连接云端统一消息中心，日常运行不依赖个人电脑、USB 或同一局域网。旧 iPad 的采集需限制并发、内存与扫描工作量，并支持断线恢复。

## 技术栈
Cloudflare Worker、D1、R2；Vue 前端与 @platform-kit/fluent；通用连接器协议。具体客户端适配器、设备身份、凭据和消息内容位于私有目录。

## 模块结构
- cloudflare-worker：云端接口与网页。
- bridge：通用连接器与运行契约。
- test：本次工作的所有测试。
- agents：工程审计记录。

## 项目规则
见 [local.instructions.md](local.instructions.md)。
