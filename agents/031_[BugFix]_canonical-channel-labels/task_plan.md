# Plan

- [x] Load the agent-mode and Cloudflare project workflows; inspect public project instructions and worktree inventory.
- [x] Create the isolated `feature/channel-labels` worktree from current `main`.
- [x] Confirm channel labels are used consistently for navigation IDs, counts, filtering, and connector detail display.
- [x] Add one shared known-label normalizer for `qq` → `QQ` and `wechat`/`微信` → `微信`, preserving all other label strings.
- [x] Add focused root `/test` coverage for aliases, unknown custom labels, connector isolation, and filter/count consistency.
- [x] Run focused tests and UI type-check/build; inspect the final diff.
