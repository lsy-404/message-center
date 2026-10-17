# Device Activity Mirror

- [x] Implement a strict root-owned atomic mirror publisher while preserving primary state writes.
- [x] Discover the canonical app-container mirror through the local adapter before native monitor startup.
- [x] Add failure, permissions, path, transition, and request-field regression tests under `/test`.
- [x] Run focused tests and inspect the final diff; commit the scoped work.
- [x] Hand off the exact device preflight requirement to the coordinator; do not access the device.
- [x] Replace the sandbox-rejected global candidate with descriptor-relative app-container publication and native POSIX race tests.
- [ ] Verify QQ can read the app-container mirror before enabling the native sender gate.
