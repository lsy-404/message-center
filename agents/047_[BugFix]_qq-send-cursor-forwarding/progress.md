# Progress

- Verified the assigned worktree is clean at the requested branch and commit. Read the agent-mode skill and public project rules.
- Confirmed scan cursor storage is connector/profile scoped, and command-ledger `done`/`started` paths return before adapter dispatch.
- Confirmed the send request is sent only through the local adapter subprocess; Worker completion remains built from the adapter result, not request contents.
- Added exact connector/profile cursor loading with the existing durable-size cap, validated v1 shape, and a fixed terminal pre-dispatch error for invalid state.
- Added the cursor to the local QQ send request only. Tests cover successful forwarding, profile/connector mismatch, missing/invalid/oversized state, exact size boundary, no Worker completion leakage, WeChat isolation, and completed-command replay after cursor removal.
- Validation: `python -m unittest discover -s test -p 'test_device_runtime.py' -q` passed 98 tests (2 skipped); `python -m unittest discover -s test -q` passed 134 tests (2 skipped); `git diff --check` passed.
