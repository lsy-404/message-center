# Findings

- The UI is a Vue page using `@platform-kit/fluent`; its conversation rows are native buttons in a plain scrollable list. No existing virtual-list or `ConversationList` abstraction is present.
- Current UI filters apply over `snapshot.conversations`; there is no text search or incremental list bound. Adding a small pure filter/paging utility allows full-dataset search while limiting rendered rows.
- Worker inbox route orders conversations by pinned/recent activity and currently caps them at 300. The separate message query is also 300 and must remain unchanged.
- Device cursor limit is `MAX_CONVERSATIONS = 200`; its serialized-size guard is independent and remains 64 KiB.
- The fluent-ui worktree had an unrelated untracked `work/` directory before task changes; it remains untouched.
