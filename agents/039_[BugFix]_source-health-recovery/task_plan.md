# Source health recovery

- [x] Read the agent-mode workflow, project instructions, public runtime state machine, and isolated test suite.
- [x] Propose the private scan success signal and align recovery trigger with the private adapter owner.
- [x] Implement online-only scan commits, per-source failure tracking, persisted recovery cooldown, and post-activation settling.
- [x] Add isolated tests for successful empty reads, cursor preservation on offline reads, bounded recovery, restart persistence, settling, and command-poll safety.
- [x] Run isolated runtime tests and review the public diff for privacy, exact wake schema, and queue/command invariants.
- [x] Commit only task-owned changes.
