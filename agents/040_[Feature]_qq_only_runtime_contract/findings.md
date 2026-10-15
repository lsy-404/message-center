# Findings
- Public runtime `DeviceRuntime.__init__` previously enabled `autoWake` only for exactly one QQ and one WeChat connector; readiness previously omitted driver.
- Runtime scan driver dispatch supports `qq` and `wechat`; per-connector `receiveOnly` suppresses text-send capability and command execution.
- Runtime advertises `receive_text` and `receive_images`; it advertises `send_text` when `receiveOnly` is not true. It does not advertise voice/video send or generic file send here.
- UI derives text and attachments from connector capability flags; Worker API gates requested sends against registered per-connector capabilities.
- Existing public audits say ordinary QQ cloud-command sending has not been end-to-end validated. This work does not enable send capability or imply physical delivery.
- Historical WeChat messages, shared channel-label support, and inbox filters are retained.
- Private adapter coordination agreed on the explicit readiness request `driver: "qq"`.
