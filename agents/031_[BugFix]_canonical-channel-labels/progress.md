# Progress

- Created `normalizeChannelLabel` in `cloudflare-worker/ui/src/conversation-list.mjs` and used it in both the application label helper and the pure conversation filter. QQ aliases now render/filter as `QQ`; WeChat aliases render/filter as `微信`; unknown labels retain the original string.
- Updated the module declaration so Vue/TypeScript consumers see the new export.
- Added `test/channel-labels.test.mjs` for known aliases, preserved custom labels, filter grouping, connector isolation, and unchanged connector/external identity values.
- Validation passed: focused Node tests (3/3), UI `pnpm check`, and `pnpm build`. Dependency installation used the local cache with `--offline --frozen-lockfile`; the lockfile is unchanged.
