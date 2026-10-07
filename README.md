# Message Center

面向自有 Agent 基础设施的通用、多账号消息中心。它把已登录客户端或云端渠道统一为连接实例，并通过出站 relay 接入 Cloudflare Worker；Agent 使用远程 MCP 领取受控事件、下载获准文件和排队回复。

## 目录

- `cloudflare-worker/`：生产 Worker、D1 schema、R2 附件接口、登录 UI、连接器协议和远程 MCP。
- `bridge/device-runtime/`：Python 3.9 设备端 HTTPS 运行器，串行调度连接实例，并持久化队列、游标和发送结果。
- `bridge/`：通用策略、MCP、连接器进程边界与其他主机渠道的 relay。

设备端运行器不要求个人电脑常驻、USB 或同一局域网。它需要设备本机已可用的私有采集适配器；配置和部署方式见 [设备端运行器](./bridge/device-runtime/README.md)。当前运行器支持文本事件，附件传输仍由现有桥接实现提供。云端 UI 使用 `@platform-kit/fluent`。

实际客户端适配器、登录态、私钥、真实配置、运行记录和下载内容不进入仓库。核心与适配器通过 [连接器契约](./bridge/docs/device-adapter-contract.md) 解耦。

## 消息触发模型

- 私聊默认产生 `direct` 事件。
- 群聊只接受个人 `mention` 或 `explicit_request`；全体提及不会触发。
- 群事件携带最多 20 条此前上下文，但正文、上下文和附件均是不可信输入，不能扩大服务端策略返回的项目或动作范围。
- 普通 `background` 群消息只抽取文字元素，每 5 分钟批量提交；不包含文件、图片、视频、语音或表情包。Worker 会把它们规范化到统一消息流，但不会放入 Agent 即时领取队列；旧备份查询端点仅作为兼容接口保留。
- 原生折叠与消息盒字段规范化为 `normal / folded / message_box / unknown`，置顶状态独立保存并用于会话排序；收件箱在可见且联网时轮询，等待当前读取结束后再刷新，隐藏/离线时暂停，恢复后立即刷新并对失败退避。
- MCP 使用 `listen_messages` 领取短期租约，以 `reply_message` 排队回复，并用 `complete_message` 完成、重试或转入人工检查。

## 验证

```powershell
Set-Location .\bridge
pnpm install --frozen-lockfile
pnpm run check
pnpm run test
pnpm run build

Set-Location ..\cloudflare-worker
Set-Location .\ui
pnpm install --frozen-lockfile
pnpm run check
pnpm run build

Set-Location ..
node --check worker/index.js
node ../test/worker-smoke.test.mjs
node ../test/inbox-refresh.test.mjs
node worker/schema-test.mjs
pnpm dlx wrangler deploy --dry-run

Set-Location ..
python -m unittest discover -s test -v
```

生产部署和密钥管理分别见 `cloudflare-worker/README.md` 与 `bridge/README.md`。公开仓库不包含运行时适配器，并且不应提交任何凭据或设备数据。
