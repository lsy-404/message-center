# Progress

- Implemented the paired binary-output CLI flags and strict descriptor validation.
- Binary mode accepts exactly one valid Frida send with a matching byte count, writes its GBytes attachment to the inherited descriptor, and reports fixed metadata only. Failure truncates the descriptor; observed duplicate sends are rejected even during cleanup.
- Updated helper documentation, the pinned iOS build workflow, artifact source/provenance hashes, and root contract tests.
- `node --test test/*.test.mjs`: 14 tests passed.
- The dedicated C test is wired into the macOS workflow. This Windows host's Strawberry GCC lacks the POSIX `fcntl`/`pread` interfaces used by the macOS/iOS test target, so that C test was not locally executable here.
- Root merged and installed the corrected helper. Bounded image export passed size and integrity validation.
