# Findings

- The v4 durable state has an exact field set in `bridge/device-runtime/device_activity.py`; the mirror must reuse it without adding a schema or changing the activity token/generation contract.
- The primary state path is runtime-local and remains mode 0600. The proposed mirror is a fixed root-owned path with 0644 state files, intended for the private adapter to read.
- Root confirmed the runtime and adapter subprocess run as UID 0, matching the private guard's `st_uid == os.getuid()` requirement. The QQ sandbox readability preflight has not passed. Production code publishes only after the fixed directory passes strict root ownership, mode, regular-file, and no-symlink checks; device activation still requires the separate reader-access preflight.
- Device access is out of scope for this task.
