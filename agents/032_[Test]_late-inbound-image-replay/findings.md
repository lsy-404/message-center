# Findings

A duplicate event with the same connector and external message ID resolves the existing message row. Newly supplied attachment IDs are merged into existing metadata only after `verifySupplementalAttachments` confirms the uploaded object, metadata, conversation binding, and message binding. The immediate-message helper then associates the file and uses `INSERT OR IGNORE` for the agent queue. The new regression exercises this path with a `[图片]` placeholder followed by an uploaded image.
