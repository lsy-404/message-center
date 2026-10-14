# 执行计划

- [x] 核对 secret helper 现有存储、stdin 上传、relay 和在线验证行为，确认不执行真实配置操作。
- [x] 设计并实现 OIDC_CLIENT_SECRET 与 SESSION_SECRET 的安全配置、存储、状态和同步；保留现有 connector/agent 值并移除 ADMIN_TOKEN/password 操作。
- [x] 更新 Worker README 与 wrangler 示例，说明 OIDC 非秘密设置、confidential client、D1 schema 和 OIDC 运维边界。
- [x] 在根 test/ 添加必要的静态运维回归检查，保留用户指定 smoke 断言。
- [x] 完成剩余差异审阅并提交当前 feature 分支；不 push、不合并。
