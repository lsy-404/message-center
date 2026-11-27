# Device adapter contract

设备适配器是被设备端运行器直接启动的独立进程，与 MCP、策略和 Agent 执行器保持进程边界。仓库内的 `bridge/device-runtime/selkies_adapter.py` 是该契约的参考实现：读取 wechat-selkies 容器中官方微信/QQ Linux 客户端的会话列表，只收不发。适配器本身不含凭据或设备数据；连接信息写在适配器旁受 `0600` 保护的本地配置中，不进入仓库。

## 进程契约

- 运行器每次调用只传一个 UTF-8 JSON 请求（stdin），适配器必须只输出一个 UTF-8 JSON 对象（stdout），诊断写 stderr，调用受超时约束。
- `scan` 返回 `sourceReadStatus` 为 `complete` 或 `failed`：`complete` 须带 `ok: true`、`health`、`cursor`、`messages`，可附 `conversationProfiles`、`active`、`more`；`failed` 须带 `ok: false`，运行器据此标记数据源失败并退避，不提交任何进度。
- `send` 不支持时返回 `{"ok":false,"dispatched":false,"error":"send_unsupported"}`，对应连接器必须配置 `receiveOnly`。
- 完整字段、限额和附件暂存规则见 [设备端运行器](../device-runtime/README.md)。

## 桥接适配器要求

经桥接核心接入的会话还须实现 `BridgeAdapter`，并满足以下入站与出站要求。

### 入站要求

适配器向核心提交规范化 `IncomingBridgeMessage`：

- 全局唯一且可去重的消息 ID。
- conversation/sender 的稳定 ID、显示名和身份可信度。
- UTC 时间、纯文本内容、附件元数据和不透明 reply handle。
- 附件先复制到 staging 根目录，计算大小和 SHA-256；不得把远程 URL直接交给 MCP。

如果只能取得群名、昵称或 OCR 文本，`assurance` 必须是 `display_only`。核心会阻止此类事件获得项目访问权。

### 出站要求

`sendReply(message, text, idempotencyKey)`：

- 只能使用消息已有的 reply handle 回复原会话。
- 必须使用幂等键避免重试导致重复发信。
- 不得提供按原始平台标识任意发送的旁路接口。
- 若实现需要激活窗口，`canSendWhileLocked` 必须是 `false`，且只能在核心返回 `away_unlocked` 时运行；检测到用户重新输入应中止并恢复原窗口/草稿。

## 可接受的接入优先级

1. 厂商公开或明确授权的本地扩展/辅助接口。
2. 用户授权、版本固定且不导出认证材料的设备运行时连接器。
3. 可访问性接口、通知接口或经过版本固定的 RPA；无法证明身份时必须降级为 `display_only`。
4. 用户离席时的受控前台自动化，带立即中止和状态恢复。

会话密钥提取、聊天数据库解密和协议中间人不属于本适配器契约。运行时连接器不得扩大到这些能力。
