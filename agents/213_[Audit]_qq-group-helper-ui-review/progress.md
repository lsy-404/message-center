# Progress

- Read `agent-mode` and `agents/local.instructions.md`.
- Created a separate review worktree from public `main`; the candidate checkout remains untouched.
- Began read-only review of the candidate commit.
- Traced `connectorKind`, `conversationType`, and `placement` from the Worker inbox projection to the new helper filter.
- Ran the candidate's targeted Node test (4/4), UI type check, and production build successfully.
- Reported a concrete empty-filter selection leak: the new entry action can retain a prior conversation as the active thread/send target.
- Reviewed follow-up `b5f4025`: it fixes empty-entry selection, preserves the previous draft cache, sets the QQ protocol filter, and moves QQ before channel labels.
- Found a second selection leak across refresh: empty local selection is replaced by the Worker default first conversation because `load('')` omits `conversationId` and `readInbox()` falls back to the first row.
