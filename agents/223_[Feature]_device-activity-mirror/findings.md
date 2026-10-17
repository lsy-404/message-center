# Findings

- Live QQ rejected the globally readable root mirror at open with EPERM despite all native wrappers being available. The reader must use QQ's own data container.
- Startup uses the configured local adapter's bounded metadata-only path discovery before creating the activity monitor. The private adapter returns a canonical app-container path with the fixed Library/MessageCenterActivity/runtime.activity.json suffix; no cloud request supplies this path.
- A root-owned mirror directory below mobile-owned app data is valid only with descriptor-relative traversal and replacement. Each directory is opened without following symlinks, the final directory/file have exact root ownership/modes, and writes/rename/fsync remain pinned to that directory descriptor. This replaces the earlier globally rooted candidate and avoids relaxing private-config permissions.

- The v4 durable state has an exact field set in `bridge/device-runtime/device_activity.py`; the mirror must reuse it without adding a schema or changing the activity token/generation contract.
- The primary state path is runtime-local and remains mode 0600. The mirror is fixed at `/private/var/MessageCenterActivity/runtime.activity.json` with a root-owned 0755 parent and 0644 file, intended for the private adapter to read.
- Root confirmed the runtime and adapter subprocess run as UID 0, matching the private guard's `st_uid == os.getuid()` requirement. The QQ sandbox readability preflight has not passed. Production code publishes only after the fixed directory passes strict root ownership, mode, regular-file, and no-symlink checks; device activation still requires the separate reader-access preflight.
- Device access is out of scope for this task.
