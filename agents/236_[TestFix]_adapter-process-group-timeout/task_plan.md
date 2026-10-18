# Plan
- [x] Inspect the failing timeout test and POSIX process-group cleanup implementation.
- [x] Replace the fixed-delay child fixture with a ready/release handshake that records owned PID/PGID, covers parent-exits and parent-waits cases, and removes the duplicated block.
- [x] Run focused runtime tests available on this host; record platform limitations and a POSIX validation command.
- [x] Review the diff and commit the scoped test/audit change.
