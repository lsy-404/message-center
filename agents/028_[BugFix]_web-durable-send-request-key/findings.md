# Findings

- The composer currently keeps a per-conversation fingerprint and request ID only in an in-memory `Map`; a reload loses it.
- `/api/messages/send` returns an accepted command with `messageId` and `commandId`. The Worker deduplicates the same key and checks that it still names the same user, conversation, body, and attachments.
- The UI response helper parses JSON but only checks HTTP success. The send handler ignores the response body and clears its in-memory key on any successful HTTP response.
- The pending-key store should persist only a fingerprint and random key; storing message text in browser storage is unnecessary.
