# OIDC 运维接入

## 目标
为 Message Center 运维脚本和 Cloudflare Worker 文档提供 OIDC confidential client 运维配置；移除密码与 ADMIN_TOKEN 登录相关操作，保留 CONNECTOR/AGENT 凭据。

## 约束
- 仅编辑 bridge/scripts/message-secrets.ps1、cloudflare-worker/README.md、cloudflare-worker/wrangler.jsonc，以及根 test/ 下必要测试。
- 不访问或更改真实 Worker secrets，不部署、不访问设备，不轮换现存凭据。
- OIDC 使用 confidential client_secret_basic；session secret 由 Worker secret 提供。
- 公共文档只用 example 域名；静态配置示例注明 provider application allow_all=false。
- 不更新 agents 根索引；任务审计文件只放在本目录。

## 技术结论
- OIDC_CLIENT_SECRET 使用 `Read-Host -AsSecureString` 接收；SESSION_SECRET 只在本地 secret store 缺失时用系统随机数生成。两者用现有 DPAPI CurrentUser store 保存，通过 Wrangler stdin 上传。
- secret 上传要求被 Git 忽略的 `wrangler.local.jsonc`。缺失 OIDC secrets 时，SyncCloudflare 先同步已有 connector/agent 凭据，再以清晰错误退出；Status 也明确显示浏览器认证不可用。
- 旧 secret store 中的 ADMIN_TOKEN 只从内存映射移除，不读取其值，不再用于登录、复制、状态或云端同步；下次写入会从 DPAPI 文件中移除该键。
- provider 的 `allow_all=false` 控制应用访问授权，与 client_secret_basic 的 confidential client 属性分开说明。
- 部署文档描述的 `/api/auth/callback`、opaque session、introspection 和 `oidc_sessions` 依赖协调端同步 Worker 实现及 schema；本分支只更新运维与文档文件。
