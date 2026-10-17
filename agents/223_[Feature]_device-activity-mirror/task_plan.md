# Device Activity Mirror

- [x] Implement a strict root-owned atomic mirror publisher while preserving primary state writes.
- [x] Wire the fixed Darwin mirror path into the native monitor lease; keep host tests isolated.
- [x] Add failure, permissions, path, transition, and request-field regression tests under `/test`.
- [x] Run focused tests and inspect the final diff; commit the scoped work.
- [x] Hand off the exact device preflight requirement to the coordinator; do not access the device.
