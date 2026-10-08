# Progress

- Confirmed `feature/device-routing` was clean and at the same base commit as local `main`; reused the worktree and created `feature/profile-avatars`.
- Read the current profile sync implementation, Worker compatibility requirements, and existing `/test/test_conversation_profiles.py` cases. No code changes yet.
- Updated `bridge/device-runtime/conversation_profiles.py`: optional avatars are strictly decoded and magic-checked; image bytes and inferred MIME, exact content length, and SHA-256 are sent through the existing no-redirect PUT. Per-image and aggregate decoded data are capped at 128 KiB, and all profiles are prepared before any network opener is created.
- Expanded `test/test_conversation_profiles.py` with valid PNG upload headers/body, absent/empty avatar behavior, malformed base64, invalid magic, per-image cap, batch cap, and no-network-on-prevalidation-failure cases.
- Focused suite passed: 11 tests. Full public Python suite passed: 59 tests, 1 platform-specific skip.
