# Source health recovery

- [x] Read the agent-mode workflow, project instructions, public runtime state machine, and isolated test suite.
- [x] Propose the private scan success signal and align recovery trigger with the private adapter owner.
- [x] Implement online-only scan commits, per-source failure tracking, persisted recovery cooldown, and post-activation settling.
- [x] Add isolated tests for successful empty reads, cursor preservation on offline reads, bounded recovery, restart persistence, settling, and command-poll safety.
- [x] Run isolated runtime tests and review the public diff for privacy, exact wake schema, and queue/command invariants.
- [x] Commit only task-owned changes.

- [x] Extend adapter cleanup to invalid output and raise wake helper deadline to cover bounded recovery stages.
- [x] Add a POSIX regression test proving invalid JSON still terminates inherited process-group children; retain existing deadline assertions.
- [x] Validate the focused suite and full public test set, then commit the follow-up.
- [x] Fix the generated POSIX child-launch script and compile both generated snippets before the platform skip.
- [x] Re-run the full public test set and commit the fixture correction.
