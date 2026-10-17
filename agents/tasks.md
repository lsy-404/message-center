# Message Center 任务追踪
> 准则版本: v0.2.2

| 编号 | 任务名称 | 任务描述 | 变更动机 | 状态 |
| :--: | :-- | :-- | :-- | :-- |
| 041 | [Feature] 收件箱外观与AI状态 | 重做收件箱视觉层级与图标，显示未读、渠道色标、AI 代发与 AI 已读状态，渲染 QQ/微信引用与小程序等卡片，并补充语义与机器可读标记 | 本人需要快速扫读信息，AI 代收代发的结果需要一眼可见，页面同时供浏览器中的 AI 读取 | ✅ 本地验证通过；Safari/iPad 实机未验证 |
| 038 | [BugFix] wake-pipe-reliability | Retry transient nonblocking adapter-pipe readiness races and categorize redacted wake failures | Avoid losing bounded wake attempts to EAGAIN and make adapter failures diagnosable without leaking private details | ✅ Locally verified |
| 039 | [BugFix] source-health-recovery | Recover bounded repeated native source read failures without cursor inactivity inference or launch loops | Improve device collection stability while keeping source reads, activation retries, and send safety bounded | 🔄 In progress |
| 037 | [BugFix] auto-wake-diagnostics | Emit one compact diagnostic when the validated wake state tuple changes | Explain silent wake failures without logging private data or repeating unchanged status | ✅ Implemented and locally verified |
| 036 | [Feature] device-auto-wake | Add opt-in device wake orchestration with bounded readiness gating | Let an unlocked device runtime restore its configured QQ and WeChat split view and resume bounded collection safely | ✅ Short-window autonomous source-to-cloud sync verified; locked/reboot/long-term behavior remains unverified |
| 001 | [Feature] 独立设备与云端体验 | 恢复设备连接、轻量采集、稳定读写与 Fluent UI | 取消电脑服务依赖并适配旧设备 | 🔄 进行中 |
| 002 | [Feature] Fluent界面 | Fluent 主题、旧 iPad 视口与有界刷新 | 统一主题并减轻绘制和网络负载 | ✅ 已完成；本地化、类型检查、构建与 Playwright 通过，长期/锁屏行为待验证 |
| 003 | [Feature] 设备直连 | 有界持久化队列与串行设备运行器 | 消除桌面运行依赖 | 🔄 双端接收已验证；微信授权发送一次端到端验证通过；QQ普通云命令仍待验证 |
| 004 | [BugFix] HTTP 客户端请求头 | 为设备 HTTPS 请求声明产品 UA 与 JSON 接受类型 | Cloudflare 对默认 Python UA 返回 403 | ✅ 已完成 |
| 005 | [Feature] 设备原生会话 helper | 有界设备注入会话与构建交付 | 消除桌面注入依赖 | ✅ 已完成，实机已验证 |
| 006 | [Feature] 有界增量游标 | 为源适配器提供按会话冻结 head、向旧分页的通用游标状态机 | 防止最新页快照跨过未读历史 | ✅ 已完成，设备真实分页已验证 |
| 007 | [BugFix] 增量扫描节奏 | 有待采集消息时缩短设备轮询间隔 | 多会话轮转时降低未完成分页等待时间 | ✅ 已完成 |
| 008 | [BugFix] 消息路由与只读接收 | 普通群聊文本走备份接口，支持禁用未验证的发送命令 | 防止已抑制消息被错误确认并允许安全接收部署 | ✅ 已完成 |
| 009 | [Feature] 有限内存启动器 | 为接收进程自身设置有限内存预算 | 解决默认6 MB导致的启动失败 | ✅ 已完成，实机启动与扫描已验证 |
| 010 | [BugFix] 完成设备采集 | 恢复卡住的源连接并完成当前发现集合增量上传 | 前台保持时仍需确认全部会话与队列收尾 | ✅ 已完成，17会话无未完成增量 |
| 011 | [BugFix] 内容显示与双端接入 | 修复群聊、乱码、图片，接入微信及发送 | 完成设备与云端的真实使用路径 | 🔄 双端接收与图片已验证；微信授权云命令一次端到端验证通过；QQ普通云命令未验证 |
| 012 | [BugFix] 群聊与媒体显示 | 修复大群详情 SQL 变量超限并支持图片内联呈现 | 用户反馈云 UI 中群聊未加载、文本乱码、图片缺失 | ✅ 群聊 GET 与图片响应已修复；源端乱码和缺图另有根因 |
| 013 | [Feature] 有界图片接收 | 设备侧流式暂存并上传图片，云端绑定至普通与群后台消息 | 在旧 iPad 上支持图片而不把整图载入内存 | ✅ 已完成 |
| 014 | [Feature] 设备会话资料刷新 | 新增有界 HTTPS 客户端同步会话名称与概要元数据 | 修正云端旧标题并持续同步会话资料 | ✅ 已集成runtime；资料同步实机通过 |
| 015 | [BugFix] 媒体可靠补录 | 按 connector 隔离暂存文件并支持同消息附件补录 | 避免文件名碰撞与旧文本消息无法补图 | ✅ 已完成 |
| 016 | [Feature] 设备驱动请求路由 | 将connector kind透传至适配器扫描和已授权发送命令 | 打通QQ/微信私有适配器与直接设备运行时 | ✅ 已集成并通过双端接收验证；微信授权发送已端到端验证；QQ普通云命令未验证 |
| 017 | [BugFix] 收件箱导航与图片正文 | 合并渠道与实例入口，并在可显示图片附件存在时隐藏图片占位符 | 避免QQ/微信导航重复和图片重复提示 | ✅ 已完成 |
| 018 | [Feature] 消息发言人头像 | 在每条消息旁显示发言人头像或首字占位，支持头像资料后到更新 | 用户需要通过头像识别消息发言人 | ✅ 已完成 |
| 017 | [Feature] 有界会话头像同步 | 在设备会话资料同步中验证并上传小型头像数据 | 让消息中心会话目录显示来源头像，同时限制旧 iPad 内存与网络开销 | ✅ 已集成并部署验证 |
| 018 | [Feature] 发言人头像同步 | 为消息发言人创建独立头像存储、上传/下载路由，并在 inbox 批量返回头像地址 | 用户希望消息旁显示说话人的头像，且成员身份不应变成会话目录项 | ✅ 已集成并部署验证 |
| 019 | [Feature] 有界收件箱容量 | 扩大会话游标及 inbox 上限，并给完整列表增加有界渲染和全量搜索 | 微信会话超过 200/300 后设备游标和云端收件箱会丢失尾部会话 | ✅ 已完成 |
| 020 | [BugFix] Adapter operation deadlines | Give scans and sends bounded operation-specific subprocess budgets | Prevent the relay from killing native scans or sends before bounded helper cleanup completes | ✅ 已集成安装并通过实机测试 |
| 020 | [BugFix] 群聊备份发言人头像 | 群聊文本备份读取接口返回发言人头像路径 | QQ 群聊备份详情缺少已同步的发言人头像 | ✅ 已完成 |
| 021 | [BugFix] 群备份重复资料刷新 | 对同一群聊消息的安全重放刷新缺失或旧 sender ID | 头像到达晚于消息入库时 inbox JOIN 无法命中 | ✅ 已完成 |
| 022 | [BugFix] 持续心跳退避 | 将设备心跳与扫描/命令退避隔离，并为心跳网络错误设置有界退避 | connector 级共享退避会在操作失败后抑制心跳并让 lastSeenAt 过期 | ✅ 已集成并安装 |
| 023 | [Feature] Helper 二进制输出 | 为单次 Frida 结果提供有界继承文件描述符输出 | 旧设备无法从运行时直接读取应用容器媒体文件 | ✅ 已部署并通过有界图片导出完整性验证 |
| 024 | [BugFix] 隔离旧发送命令 | 在 connector 开启 send_text 时隔离原有待发与租约命令 | 防止启用发送时旧命令自动执行 | ✅ 已部署；遗留待发消息保留为人工复核且 API 确认未执行 |
| 025 | [Feature] 显示发送状态 | 在出站消息中显示等待、成功、失败和待确认状态 | 避免把排队或结果不确定的消息误认为已发送 | ✅ 已部署，Fluent 状态显示验证通过 |
| 024 | [BugFix] Outbox delivery heartbeat progress | Let successful current-pass delivery keep its connector heartbeat online during source backlog catch-up | Source backlog can outlast the scan freshness window despite relay ACK progress | ✅ 已集成并安装；命令门控仍要求 source health 与扫描新鲜度 |

| 026 | [Chore] Verification status reconciliation | Reconcile public audit summaries with deployed integration and current validation evidence | Remove stale local-only and receive-only status while preserving explicit validation limits | ✅ 已完成 |

| 027 | [Chore] 离线回归验证 | 对当前公开 main 执行 Python、Node、schema、Fluent 与 Safari 15 UI 回归 | 完成用户要求的公共仓库离线测试并明确真实 UI 验证边界 | ✅ 全部离线测试通过；Safari/iPad 实机未验证 |

| 028 | [BugFix] web-durable-send-request-key | Persist and reuse a send request key across reload/network error until Worker acceptance is confirmed | Prevent duplicate queued sends after a lost HTTP response | 🔄 进行中 |
| 029 | [Feature] Frida eternalized-script-helper | Add opt-in generic persistent-script lifecycle support to the native helper | Keep a coordinator script alive across short-lived Frida sessions without changing default helper cleanup | 🔄 进行中 |

| 030 | [BugFix] Native helper eternalize acknowledgement | Attempt a generic script event after persistent lifetime is established | Prevent callback pointers from being published before helper lifetime is confirmed | ❌ 已废弃；runtime 验证表明 eternalize 后的 post 未送达 |

| 031 | [BugFix] Canonical channel labels | Normalize known QQ and WeChat aliases consistently across navigation and filtering | Duplicate channel buckets caused by free-form casing and language labels | ✅ Completed |
| 032 | [BugFix] Native media outbox enrichment | Allow a same-ID event with newly validated attachments to enrich an attachment-free durable outbox row atomically | Native receive may first persist a text placeholder before media staging completes | ✅ Completed; full Python tests pass |
| 033 | [Feature] admin-oidc | Replace human password access with administrator-only confidential OIDC login | Use the existing auth provider and private client requested by the user | ✅ Deployed; live login, refresh and denial verified; manual logout user-confirmed, browser automation blocked |
| 034 | [Feature] oidc-session-module | Add strict confidential OIDC and encrypted server sessions | Require live admin authorization and serialize rotating refresh tokens | ✅ Integrated and locally verified |
| 035 | [Feature] oidc-ops | Configure OIDC secrets and document private deployment | Keep secrets in protected storage and preserve independent machine credentials | ✅ Integrated and locally verified |

| 038 | [BugFix] oidc-refresh-recovery | Preserve valid sessions through optional/ambiguous token refresh and restore browser reauthentication flow | Users receive auth_refresh_failed after sessions age; classify refresh failure and route terminal browser auth correctly | ✅ Implemented and locally verified; deployment pending coordinator |
| 040 | [Feature] QQ-only runtime contract | Align readiness with QQ-only operation and record public contract boundaries | Enable supported QQ independently without overstating send validation | ✅ Complete; 72 runtime tests pass (2 platform skips) |
| 041 | [BugFix] QQ native attach recovery | Trigger bounded QQ app reactivation after consecutive explicit native attach failures | Current read recovery does not reactivate after repeated confirmed attach failures; reject ambiguous failures and preserve send/cursor safety | 🔄 In progress |
| 042 | [BugFix] Receipt native-ID reconciliation | Associate confirmed QQ sends with their exact source-derived event ID and deduplicate self events | Outbound rows retain a null native ID after confirmed sends, leaving a potential cross-path duplicate | 🔄 In progress |
| 043 | [BugFix] QQ retry and receipt conflict | Prevent contradictory retry acknowledgements from requeueing confirmed or uncertain QQ sends | A retry flag currently takes precedence over successful delivery evidence | ✅ Implemented and locally verified |
| 044 | [BugFix] Self group event routing | Deliver self-authored background group events through normal event ingestion | The legacy group-backup route classifies all background group records as inbound and rejects some media | 🔄 In progress |

| 045 | [BugFix] wake-readiness-heartbeat-freshness | 刷新长步骤后的 readiness 并在真实 outbox ACK 后及时更新心跳 | 慢上传和慢扫描跨越心跳/ readiness TTL 后被显示为离线或关闭后续门禁 | 🔄 进行中 |

| 046 | [BugFix] QQ query pending recovery | Recover only after repeated exact pending-gate evidence for the same QQ PID | A pinned callback gate can otherwise remain occupied while generic active-app wakeups leave QQ running | 🔄 进行中 |

- 047_[BugFix]_qq-send-cursor-forwarding: Forward the current connector/profile cursor only in the local QQ send adapter request, with strict scope and replay guards.

| 048 | [BugFix] Adapter send timeout | Give the public runtime 10 seconds of return margin above the private 120-second bounded QQ send path | Prevent the runtime subprocess deadline from expiring before a verified send returns | ✅ Completed; runtime tests pass |
| 049 | [Feature] QQ confirmed-send priority read | Register locally verified QQ send receipts as bounded read-priority metadata on the same connector/profile cursor | Ordinary round-robin reads may take too long to observe a newly confirmed self-message | ✅ Host tests pass; local commit ready for integration |

| 050 | [BugFix] QQ confirmed-send alias contract | Register confirmed QQ reads using the canonical conversation external ID in Worker commands | The runtime expected a profile prefix that the Worker and adapter do not add to conversation IDs | ✅ Locally verified |
| 213 | [Audit] QQ group helper UI review | Review the candidate QQ group-helper inbox UI for classification, state flow, and old-iPad-safe rendering | Verify the new UI preserves existing inbox behavior and excludes unrelated sessions | ✅ Completed |
| 195 | [BugFix] QQ create_script timeout recovery | Accept only explicit pre-dispatch QQ create_script timeouts and route them through existing same-PID bounded recovery | Repeated Frida script-creation timeouts need the existing safe QQ recovery path | ✅ Locally verified |
| 212 | [Feature] QQ 群助手入口 | 在收件箱提供 QQ 折叠/消息盒子群的独立入口，保持现有搜索、未读和聊天选择流程 | 群目录已同步但 folded/message_box 会话缺少可进入的用户界面 | ✅ Completed |
| 215 | 215_[Audit]_qq-graytip-presentation | Adversarially review the optional QQ system graytip presentation path from Worker through the device runtime | Ensure only the verified QQ system source upgrades the exact stored type-8 body while all other messages remain unchanged | ✅ Completed |

| 214 | [Feature] QQ gray-tip presentation | Carry an explicit QQ system marker through ingestion, safely upgrade exact legacy placeholders, and render centered system text | QQ gray-tip records need system presentation without inferring from type/body or changing sender identity | ✅ Completed |

| 221 | [BugFix] QQ sticker content and quote preview | Render explicitly classified QQ stickers within a compact display box, validate inbound attachment bytes and preserve structured quote content | Image stickers can render at full image size and attachment/reply metadata must cross Worker/UI boundaries safely | 🔄 Public changes locally verified; native image discovery and browser proof remain with root |
| 216 | [Feature] device-human-idle | Monitor HOME and digitizer activity on-device; pause scans, commands, and auto-wake until a continuous 180-second idle interval | Protect human app use while resuming safe QQ collection after idle; retain outbox delivery | 🔄 In progress |

| 222 | [BugFix] QQ inbound backpressure | Separate durable outbox delivery retries from inbound source scanning while retaining bounded capacity and cursor atomicity | A single unacknowledged queue row currently blocks all new scans for its connector | ✅ Locally verified and committed |
| 230 | [Diagnostic] HID touch entitlement probe | Build a short-lived iOS event-type monitor that reports only its own effective HID event-monitor entitlement and restricted-entitlement validation status | Distinguish runtime entitlement state from missing touch callbacks without changing production processes | 🔄 In progress |

| 223 | [Feature] device-activity-mirror | Publish the exact v4 activity lease to a validated root-readable atomic mirror for the private sender | The sender needs a durable local activity guard without access to the primary 0600 runtime state | 🔄 In progress |
