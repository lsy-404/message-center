# Task plan

- [x] Confirm the public repository, base commit, and isolated worktree.
- [x] Inspect runtime scan, queue capacity, upload retry, and regression-test contracts.
- [x] Separate outbox delivery retry from source scan retry while preserving durable queue semantics.
- [x] Remove the pending-row scan gate and test pending upload failure, bounded capacity, and cursor durability.
- [x] Run focused and full runtime tests; inspect the final diff for scope and metadata violations.
- [x] Commit the verified change locally without pushing or merging.
