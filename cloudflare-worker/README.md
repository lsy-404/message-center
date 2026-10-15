# Message Center

`message.example.com` 是一个完全运行在 Cloudflare Worker 上的统一消息中心。一个 Worker 同时提供前端、HTTP 接入协议与远程 MCP；D1 保存规范化消息、策略、队列和审计记录，R2 保存私有附件。

## 运行架构

- `worker/index.js`：唯一生产运行时入口；不依赖 Pages、Sites、服务器或入站设备端口。
- `ui/`：Vue 3 + Vite 前端。Worker 在认证后通过静态资产绑定返回带哈希的构建产物；页面与 API 均显式禁用缓存。图标为内联的 Fluent UI System Icons；会话行与消息带 `data-*` 状态属性、`<time datetime>` 时间与 ARIA 语义，供浏览器中的 AI agent 直接读取。收件箱在页面可见且联网时轮询，请求结束后才安排下一次刷新；失败时指数退避至最多 60 秒，页面隐藏或离线时暂停，恢复后立即刷新。
- `worker/schema.sql`：D1 schema。`connector_instances` 是连接实例表，不对渠道类型设置唯一约束。
- `connector_layout_control` 只服务于显式声明 `layout_control` 的单一设备 owner；云端使用 revision 做 CAS，设备本地动作另用持久化 generation 与 action ID 排序、去重。
- `wrangler.jsonc`：本地开发与 Wrangler 生产部署配置。
- 客户端登录态和供应商凭据只保留在设备 relay 或对应云 relay 中。
- relay 只向 `message.example.com` 发起出站 HTTPS。

## 多账号与能力声明

每个接入实例包含独立的 `id`、`kind`、`accountLabel`、`displayName`、`note`、`mode` 与能力列表。例如同一渠道可以同时注册个人账号和团队账号；一个短信号码可以只声明 `receive_text`，而另一个实例可以声明收发及附件能力。

当前标准能力：

- `receive_text` / `send_text`
- `receive_files` / `send_files`
- `receive_images` / `send_images`
- `receive_video` / `send_video`
- `threads` / `reactions`
- `layout_control`（仅 `device_relay`；每台物理设备只允许一个 owner）

发送 API、网页输入框和 MCP 回复都会检查目标实例的实际能力。
原生表情目前只能作为文本占位摘要入库，未实现独立媒体对象的收发，因此不声明表情收发能力。

## 鉴权

- 网页与人工 API：`/login` 发起 OIDC Authorization Code + PKCE，身份提供方回调 `/api/auth/callback`。浏览器只保存 opaque、HttpOnly、Secure、SameSite Cookie；D1 `oidc_sessions` 保存服务端会话。会话最长 12 小时并在有效期内刷新，每次受保护请求都通过 token introspection 检查 `active`、`client_id`、`sub` 和 `roles`，仅接受 `roles` 含 `admin` 的账户。ID Token/UserInfo 的普通资料字段不用于管理授权。OIDC 配置或必需 secret 缺失时浏览器认证失败关闭。
- OIDC 非秘密变量为 `OIDC_ISSUER`、`OIDC_CLIENT_ID` 和 `OIDC_REDIRECT_URI`；本仓库的公开配置只放 `example.com` 占位值。为实际站点在私有 `wrangler.local.jsonc` 填写自己的 issuer、客户端 ID 和精确回调 URI。身份提供方登记的客户端必须是 confidential client，认证方法为 `client_secret_basic`，精确回调 URI 为 `https://message.example.com/api/auth/callback`（生产环境替换域名）；admin-only 应用将 provider 上的 `allow_all` 设为 `false`，并确保没有非管理员账户的显式 allow assignment。`allow_all` 是应用访问策略，与 OAuth 客户端是否 confidential 是不同设置。
- `OIDC_CLIENT_SECRET` 与 `SESSION_SECRET` 是 Worker secrets，不能放入 `vars`、仓库、命令参数或日志。会话密钥独立于 OIDC 客户端密钥。Cloudflare Access 可以作为额外网络边界，但不能替代 Worker 的 OIDC 会话和管理员角色验证。
- 设备/云 relay：生产环境使用 `CONNECTOR_TOKENS` JSON secret（`connectorId -> token`）。每个请求必须同时携带 `x-connector-id` 和该实例的 bearer，实例之间不能互相冒充。迁移期若确实只接一个实例，可同时设置 `CONNECTOR_TOKEN` 与 `LEGACY_CONNECTOR_ID`；未绑定实例的旧 token 不会被接受。
- MCP agent：`AGENT_TOKEN` bearer。
- `CONNECTOR_TOKENS`、`CONNECTOR_TOKEN`、`AGENT_TOKEN`、`OIDC_CLIENT_SECRET` 和 `SESSION_SECRET` 都必须作为 Worker secrets 注入，源码和日志中不保存。
- 会话默认不可信，只有显式策略才能赋予 agent 项目、动作和回复范围。

## Agent 消息触发

- 私聊默认进入 Agent 队列。
- 群聊只有个人原生提及、配置的提及词或显式请求前缀才进入队列；全体提及不触发。
- 提及与显式请求附带最多 20 条此前消息上下文。上下文与正文同样是不可信输入，不会扩大项目和动作授权。
- 普通群聊只提取纯文本，每 5 分钟批量写入统一消息流，并标记 `queue_class=background`；不包含文件、图片、视频、语音或表情包，默认保留 30 天。后台消息和即时消息在收件箱中等价展示，但后台消息不能进入 Agent 即时队列。
- 原生折叠与消息盒字段规范化为 `normal`、`folded`、`message_box` 或 `unknown`；原生置顶独立规范化为 `is_pinned`。网页按置顶优先排序并显示状态，但不会把接入实例名称重复写入会话行或消息详情。
- 远程 MCP 使用 `listen_messages` 非破坏性查看即时候选、`claim_message` 原子领取、`consume_message` 完成或释放租约，并通过 `reply_message` 形成双向回复；旧工具名保留为兼容别名。
- inbox 消息附带只读的 `authorRole`（`contact`、`owner` 或 `agent`）与 `agentState`（`agent_queue` 状态，未入队为 `null`），不返回 Agent consumer ID。网页据此区分 AI 代发与本人发送，并在入站消息下显示等待 AI、AI 处理中、AI 已处理或需人工处理；会话头部汇总当前线程的这些状态。

详细协议见 [CONNECTOR_PROTOCOL.md](./CONNECTOR_PROTOCOL.md)。

## 发送与文件生命周期

- 浏览器先把附件写入私有 R2 staging，再用稳定的 `clientRequestId` 原子排队；同一请求的并发重试只会生成一条消息和一条命令。
- staging 文件最长保留 24 小时；成功排队后转为命令附件，取消或过期文件由 Worker 定时清理。
- 排队操作保证幂等。设备 relay 在本地持久化执行账本；只有明确未调用客户端时才自动重试。客户端调用结果不确定时转入人工检查，避免一次物理发送被重复执行。

## 构建与部署

公开的 `wrangler.jsonc` 只包含示例域名和零值 D1 ID。生产部署前将其复制为被 Git 忽略的 `wrangler.local.jsonc`，填写自己的 Worker、路由、D1 与 R2 资源，并在 Wrangler 命令中使用 `--config wrangler.local.jsonc`；不要把部署标识或 secret 提交到仓库。

OIDC browser session 使用 `worker/schema.sql` 中的 `oidc_sessions` 表；首次部署或更新 schema 时，使用本地配置把幂等 schema 直接应用到指定 D1，不创建 Wrangler migration：

```powershell
pnpm dlx wrangler d1 execute message-center --remote --file worker/schema.sql --config wrangler.local.jsonc
```

在 provider 创建 confidential client 并取得客户端 secret 后，可运行 `bridge/scripts/message-secrets.ps1 -Action ConfigureOidcSecrets` 通过隐藏的 SecureString 提示配置 `OIDC_CLIENT_SECRET`；脚本为首次缺失的 `SESSION_SECRET` 生成随机值，DPAPI 加密保存在当前 Windows 用户的本地 secret store，并通过 stdin 上传到 Wrangler。上传要求已配置的 `wrangler.local.jsonc`。设备 connector 与 agent secrets 独立保留；首次缺少 OIDC secrets 时，脚本会明确报告浏览器认证仍不可用，不会阻止 connector/agent secret 同步。

```powershell
Set-Location .\ui
pnpm install --frozen-lockfile
pnpm run check
pnpm run build

Set-Location ..
pnpm install --frozen-lockfile
node --check worker/index.js
node ../test/worker-schema.test.mjs
node ../test/worker-smoke.test.mjs
pnpm dlx wrangler deploy --dry-run
```

生产部署时，已有业务 schema 仍须按“远程备份并核对 pending migration → 远程应用 `migrations/`”顺序更新。`oidc_sessions` 是 `worker/schema.sql` 中的幂等建表项，不新增 migration；在部署依赖该表的 Worker 前，使用上面的 `wrangler d1 execute` 命令直接应用 schema。确认业务 migrations 和 OIDC 表均已生效后再运行 `wrangler deploy`。前端以 `@platform-kit/fluent` 的 Fluent Theme、颜色令牌和 Vue 控件为视觉基础；第三方许可与归属说明随 Worker 提供于 `/vendor/fluent/`。UI 保持原生滚动与轻量卡片布局，避免大面积模糊效果以照顾旧款 iPad。
