# Findings

- [现象] 群助手 currently appears as a separate sidebar navigation item with its own boolean view mode. [结论] It must become a folder row in the QQ channel's conversation list so the channel remains the only top-level entry.
- [数据契约] `/api/inbox` already returns each conversation's `connectorKind`, `connectorId`, `conversationType`, and `placement`; current folder membership can be determined from QQ + group + `folded`/`message_box` without a Worker schema change.
- [边界] `placement` describes QQ placement, not parent-folder identity. Do not create “folded group” or “message box” child folders from it. The group assistant opens directly to its matching conversations.
- [层级] Root → QQ group assistant is the only evidenced nested path today. Limit navigation to three list levels, but render level three only if a future explicit folder-parent field exists; this task adds no such field.
- [筛选与选择] Search/unread filters must be applied within the active channel and list path. Refresh selection must keep the selected conversation only when it remains in that scope, and selection from the assistant must retain its path ownership.
- [规则文件] The repository references `agents/local.instructions.md`; it is present and was read. The repo-root `local.instructions.md` path is absent.
