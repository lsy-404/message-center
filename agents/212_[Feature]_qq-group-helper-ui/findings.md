# 调研发现

- Worker `/api/inbox` 在 `cloudflare-worker/worker/index.js` 查询 `k.kind AS connector_kind`，映射为 UI `connectorKind`；conversation projection 同时返回 `conversationType`、`placement` 和 `unreadCount`。协议 kind `qq` 是分类依据，`channelLabel` 是可自定义显示名。
- `conversationType` 必须为 `group`，且 `placement` 必须为 `folded` 或 `message_box` 才进入助手；普通群、私聊、未知 placement 及其他 connector 不纳入。
- `filterConversations()` 原先只有 connectorId/channel/search/unread 条件；新增 connectorKind 条件让总 QQ 列表也按协议字段筛选。搜索字段与现有所有列表一致。
- UI 选择仍经 `selectConversationById()` / `selectConversation()`；本次不改发送、Worker schema、适配器或配置。
- 首轮检查发现新 `connectorKind` 条件少了局部取值声明，Node 测试直接报 `ReferenceError`；补齐后相关测试全通过。
- 首轮安装前 UI check/build 因 worktree 无 `node_modules` 失败；依据已锁定依赖文件离线安装后 check/build 通过。Worker 集成测试也因缺 `openid-client` 失败；在 `cloudflare-worker` 按 lockfile 离线安装后测试通过。
- 视图切换需复用筛选无结果时的选择状态转移：保留范围内选择、否则选择首个匹配项、候选为空则清空会话与composer/read状态。`resolveConversationSelection()` 将该分支抽为纯函数供实际UI入口和测试共用。
- inbox refresh 在未传 conversationId 时可能返回全局首会话；助手视图必须按当前助手筛选再次解析响应，空范围强制保留空选择，发现新匹配群后以该群 ID 发起精确详情读取。
- 搜索/未读改变助手范围时也需立刻应用相同选择迁移；否则列表空了仍可能保留范围外编辑器。
- 窄pane中通用 `.quiet-button` 固定34px宽，长返回文案因此逐字换行；返回控件应使用独立紧凑宽度和 `white-space: nowrap`，通过短显文案保留完整无障碍名称。
