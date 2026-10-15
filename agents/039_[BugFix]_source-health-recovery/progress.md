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
- Follow-up public scan contract now requires exact boolean `sourceReadOk`. Verified reads with `health: degraded` commit validated page/cursor/media queue progress and clear read-failure streak without app recovery; explicit false is a read failure; missing or non-boolean is an invalid adapter response.
- Updated all public runtime scan fixtures and added regression cases for degraded-but-successful media backlog, explicit failed reads, and missing contract field. Runtime suite passes 71 tests with one platform skip; full public `/test` suite passes 104 with one platform skip.
- Independently reviewed private cache commit `b8a138f`: cache hits still perform the selected bounded page read; caches bind profile/PID/filters and expire after 60 seconds; both caches are capped at 24 KiB and cursor budgets stay bounded at 65,536 bytes. The TTL bounds staleness, though QQ discovery prioritization can lag for cache-valid periods and idle scan cadence can exceed TTL.

- Increased public wake helper timeout from 20 to 30 seconds and updated its runtime timeout expectation to match the bounded multi-stage recovery contract.
- Moved exit-code, JSON decode, and response-shape validation into `run_adapter` cleanup scope. Added a POSIX child-leak regression test for invalid JSON and corrected its generated script to contain actual line breaks. Existing oversized-input/output and early-closed-stdout assertions were preserved.
- `py -m unittest test.test_device_runtime`: 72 tests passed, 2 platform-specific skips on Windows. POSIX process-group behavior still requires the parent isolated iPad rerun.
- Corrected the generated child-launch script syntax and added `compile()` checks for both child and adapter snippets before the POSIX-only execution skip. Focused fixture test compiles then skips on Windows; full `/test` suite passes 105 tests with 2 platform-specific skips.
