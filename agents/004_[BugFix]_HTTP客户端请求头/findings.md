# Findings

- 已知设备运行环境使用 Python 3.9 的默认 urllib User-Agent 时，本站返回 HTTP 403 / Cloudflare code 1010；明确声明 `User-Agent: MessageCenterDevice/1.0` 与 `Accept: application/json` 后 healthz 返回 200。没有验证码，也不需要修改防护规则。
- 请求入口统一在 `Relay.request()`；将固定头放入该入口，能覆盖 health、events、heartbeat、command claim/lease/complete 请求，同时保留 connector token 与 connector ID。
- 回归测试应构造实际 `urllib.request.Request` 并通过实际构建的 opener 路径捕获请求头，避免只验证未被请求使用的字典。
