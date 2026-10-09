# Progress

- Verified `main` at `b14c718`, tracking `origin/main`, clean; confirmed existing worktree inventory and created an isolated branch from that head.
- Inspected composer request-key handling, API response parsing, Worker send acceptance shape, and existing UI dependency/test layout.
- Proposed a hash-only local pending-key record and durable-ID acceptance gate to root; no production code changed yet.
- Added the browser helper, composer integration and synthetic root test coverage. The helper persists only a SHA-256 fingerprint plus request UUID, requires storage before POST, and removes only the matching key after `ok` plus durable message/command IDs.
- `node --test test/web-send-request-key.test.mjs`: 4 passed. `pnpm check` and `pnpm build` passed after installing dependencies from the local pnpm cache with `--offline --frozen-lockfile`; no lockfile change.
