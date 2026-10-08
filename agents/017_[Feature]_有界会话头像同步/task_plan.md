# 017 有界会话头像同步

## Scope
Extend public device-runtime conversation profile synchronization to accept optional bounded base64 avatars and upload raw validated image bytes through the existing Worker profile endpoint. Keep redirect refusal and validate the entire batch before network activity.

## Plan
- [x] Verify the reused worktree is clean, `main` shares its base commit, and create the requested feature branch.
- [x] Review the existing profile sync and root test contracts.
- [x] Add strict image decoding, MIME magic detection, digest and body headers, per-image and batch decoded-byte caps.
- [x] Add root `/test` coverage for valid, absent, malformed, oversized, batch-capped, and invalid-magic avatars.
- [x] Run focused and full public Python tests, review the diff, and commit locally.
