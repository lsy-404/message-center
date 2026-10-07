# 调查发现

- Worker profile 路由是 `PUT /api/connectors/conversation-profiles/{conversationExternalId}`。文本型 header `x-conversation-display-name`、`x-conversation-channel-label`、`x-conversation-last-preview` 必须用 `decodeURIComponent` 对应的 UTF-8 percent encoding。
- Worker 接受的类型为 direct/group/unknown，placement 为 normal/folded/message_box/unknown；pinned 为 0/1；unread count 最多 7 位，last-at 与 unread-observed-at 必须是可解析时间。
- 现有 Relay 请求器使用 HTTPS、产品 User-Agent、Accept、connector Authorization、NoRedirect、20 秒超时和 1 MiB 响应上限。新 PUT 必须显式发送空 body，使 Content-Length 为 0。
- 独立模块不修改 `device_runtime.py`；调用者应在扫描返回时同步 profile，任何请求错误必须抛出供调用层阻止 cursor commit。
- Python `urllib.request.Request(data=b"")` 不会自动添加 `Content-Length: 0`；实现显式写入该 header，确保 Worker 收到空头像 body 的 PUT。
- 整批 profile 在发起 HTTP 前完成验证；单次请求失败即抛错停止剩余请求，已成功的 PUT 可幂等重放。
