# Message Center
> 最后更新：2026-10-08

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

## 当前验证状态
- Worker 已部署集成版本 `1c72da3a-1bc7-426f-a79d-d1f4f078aa50`。收件箱导航、图片占位处理、会话与发言人头像、发送状态及有界列表已集成；Fluent 本地化、类型检查、构建与 Playwright 验证通过。
- 公开自动化验证记录：Node 测试 19 项与 Worker schema 检查通过；集成根测试 102 项通过。另有一轮公开根测试 71 项通过、1 项平台专属跳过。
- 设备 runtime 的独立心跳退避及本轮 outbox ACK 在线进展已安装；ACK 只影响 heartbeat 展示，命令轮询仍要求 source health 与扫描新鲜度。
- 有界 helper 二进制输出的严格布尔回执修正已安装，图片导出通过尺寸与完整性校验；不在公开项目记录中描述私有适配器实现。
- QQ 与微信接收和图片采集均已验证。微信发送已启用；一条早先遗留待发消息及原载荷保留为人工复核，API 查询确认未执行。唯一一次授权目标发送在 Worker 显示 delivered，随后原生最新页只读回读确认新的本人文本记录，接收器已恢复。
- QQ 授权 UI 操作有截图确认；普通 QQ 云命令发送路径仍未完整验证，不得据此重发或宣称已验证。
- 最近受控入站采集持续 44.24 秒：QQ/微信均 healthy，outbox 为 0、command ledger 为 1，期间没有新 command dispatch，接收器恢复。两端发言人头像 GET 返回 200，MIME、预算及 SHA 校验通过。
- 最近收件箱目录快照为 313 个会话、165 个群聊、52 个头像；头像覆盖仍不完整。
- 原生 SplitView 的复核中，两侧 application state 为 0、视口各为 507×768。只读 daemon 快照 outbox 与错误日志均为 0，RSS 为 18,672 KiB，进程限制为 64 MiB。CPU 样本来自重启扫描阶段，不代表稳定负载。
- 普通 daemon 后续快照中 QQ/微信均 online；receiver 无需手动 collect 即完成同步。Windows 旧 relay 任务处于 Disabled 且没有匹配进程，临时 Vite preview 已关闭，daily device-to-cloud 链路不依赖电脑常驻 relay。
- 所有在线、队列及 SplitView 记录均为受控时间点快照；长期运行和锁屏状态尚未验证。
