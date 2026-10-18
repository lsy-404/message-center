# Task plan

- Add a strict predicate for confirmed-result unload cleanup timeout with ordered bounded phase metadata.
- Thread the predicate through private producer/state persistence and public consumer recovery.
- Add malformed and same-PID restart/command/media gate tests.
- Run targeted host tests and commit locally.
