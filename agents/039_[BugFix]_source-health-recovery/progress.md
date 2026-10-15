# Progress

- Began in the dedicated `fix/source-health-recovery` worktree at the public main baseline; initial working tree was clean.
- Read `agent-mode/SKILL.md`, `agents/local.instructions.md`, public runtime wake/scan state, and the repository-root runtime tests.
- Coordinated with private recovery/cache owners: public uses `health == "online"` as proof that native discovery and page read both succeeded; successful empty online pages remain valid. Non-online results do not commit cursor/messages/profile/media state.
- Implemented persisted per-source last-success/failure streak, 3-failure threshold, 5-minute recovery cooldown, targeted `ensure-active` request with fixed `reason=read_failure` and `driver=qq|wechat`, and 60-second activation settling. Default wake response remains exact four-key schema.
- Added runtime tests for failed-read cursor preservation, successful empty read reset, bounded targeted recovery, restart-persisted failure/cooldown/settling, and command-poll suppression during recovery.
- Verification: `python -m unittest discover -s test -p 'test_*.py'` passed 100 tests with 1 platform skip; `py_compile` and `git diff --check` passed.
- Public-only change is ready for a scoped commit; no device/cloud access, deployment, push, merge, or private adapter edit was performed.
