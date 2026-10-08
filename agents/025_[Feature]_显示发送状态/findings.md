# 调查结果

- `cloudflare-worker/worker/index.js` 的 `readInbox` 已从 `messages.delivery_state` 映射到响应的 `deliveryState`。
- `cloudflare-worker/ui/src/App.vue` 的 `Message` 类型未声明该字段；`sameInbox` 逐消息比较也未比较它，因此仅状态变化的刷新会保留旧快照。
- 消息行有 Fluent 风格的 `message-meta` 文本区，可在出站消息元信息中增加小型状态文字，不需要新交互或轮询。
- `test/ui-navigation-media.cjs` 已用 Playwright 真实渲染 Vue 页面并模拟 inbox 刷新，适合增加状态行为断言。
