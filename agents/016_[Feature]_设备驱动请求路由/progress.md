# Progress: Device Driver Request Routing

- 2026-10-07: Inspected the clean `main` base and existing `device-runtime` worktree; created a separate feature worktree from the requested base commit. Read runtime and private adapter contracts. No device operations or sends performed.
# Device driver routing

- Runtime scan requests now carry the selected connector `kind` as required `driver`; unsupported kinds fail closed.
- After command lease validation and durable `started` ledger insertion, runtime send requests carry the same driver, canonical conversation ID, and authorization facts. No UI confirmation is added because the cloud command itself is the explicitly authorized operation.
- The private adapter validates `profile:conversation-[hex]`, exact target and body, and both authorization fields. QQ confirmed receipts remain distinct from no-start and uncertain outcomes; WeChat send stays disabled pending native success verification.
- Validation: public root suite 54 passed, 1 POSIX-only skip; private adapter suite 57 passed; adapter dispatch integration suite 11 passed; private adapter py_compile passed; public `git diff --check` passed.
- Private adapter and its tests live outside this public worktree and are not included in the public commit.
- 已集成到当前 main 并部署；QQ 与微信真实接收采集成功，微信保持 receive-only。云端命令发送路径未完整验证。
