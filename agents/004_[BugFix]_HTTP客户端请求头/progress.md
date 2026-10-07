# Progress

- 确认 worktree `feature/device-runtime` 干净，位于 `b50bcc2`；本地 `main` 为 `54db341`。
- 按要求将 worktree fast-forward 到 `main`，新建 `feature/device-http`。
- 在统一 HTTPS 请求头中加入固定产品 UA 和 JSON Accept；Bearer token、connector ID 仍沿用原值。
- 添加本地 HTTP server 回归测试，实际经过 `urllib.request.Request` 和 opener 后核验收到的请求头。
- Python 3.11.9 运行根级运行器 suite：26 项，25 通过，1 个 POSIX-only subprocess 测试按平台跳过；新增请求头测试通过。
- `git diff --check` 通过；提交仅包含设备运行器请求头、对应根级回归测试和本任务审计记录。
