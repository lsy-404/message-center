# Progress

- Began in the dedicated `fix/source-health-recovery` worktree at the public main baseline; initial working tree was clean.
- Read `agent-mode/SKILL.md`, `agents/local.instructions.md`, public runtime wake/scan state, and the repository-root runtime tests.
- Coordinated with private recovery/cache owners: public uses `health == "online"` as proof that native discovery and page read both succeeded; successful empty online pages remain valid. Non-online results do not commit cursor/messages/profile/media state.
- Implemented persisted per-source last-success/failure streak, 3-failure threshold, 5-minute recovery cooldown, targeted `ensure-active` request with fixed `reason=read_failure` and `driver=qq|wechat`, and 60-second activation settling. Default wake response remains exact four-key schema.
- Added runtime tests for failed-read cursor preservation, successful empty read reset, bounded targeted recovery, restart-persisted failure/cooldown/settling, and command-poll suppression during recovery.
- Verification: `python -m unittest discover -s test -p 'test_*.py'` passed 100 tests with 1 platform skip; `py_compile` and `git diff --check` passed.
- Public-only change is ready for a scoped commit; no device/cloud access, deployment, push, merge, or private adapter edit was performed.
- Review follow-up removed the requirement for a prior successful read, so repeated explicit failures on a fresh install can reach the bounded recovery threshold.
- A `None` scan result from outbox backpressure preserves scan health, timestamps, retry counters, and any forced scan request. The command loop now explicitly observes persisted startup/recovery settling too.
- Recovery-state SQLite failures are recorded as non-durable and suppress activation until state can be persisted; they do not escape the pass and prevent heartbeat processing.
- Added regression coverage for forced-scan backpressure preservation and startup-settle scan/command suppression. Focused runtime suite: 69 tests passed, 1 platform-specific skip.
- Read-only review of private wake commit `7393e62`: fixed `qq`/`wechat` aliases, existing saved-layout uniqueness, lock/overlay/transition/process-state gates, bounded native helper and activation timeouts, and durable activation budget are retained. It does not force-kill or alter response shape. Malformed unhashable `reason`/`driver` values may raise before validation completes in the private dispatcher/helper; the public caller sends only fixed strings. Reported to coordinator as hardening caution, not edited here.
- Real-device recovery remains unverified; no live device/cloud actions were performed.
