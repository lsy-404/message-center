# Progress

- Inspected runtime connector construction, Worker command construction, and private adapter event identifiers.
- Confirmed the profile-prefixed command fixture does not match the production conversation-ID contract.
- Changed `qq_command_conversation_alias` to accept only canonical raw aliases and updated the confirmed-send process/queue test to use the Worker command shape.
- Updated command/event fixtures in `test/test_device_runtime.py` to use raw conversation aliases.
- Ran `python -m unittest discover -s test -p test_device_runtime.py`: 106 passed with 2 skips; `git diff --check` is clean.
