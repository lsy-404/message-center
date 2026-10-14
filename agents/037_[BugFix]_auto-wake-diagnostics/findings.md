# Findings

- The runtime already receives validated readiness, attempted, and bounded reason values in `ensure_active`.
- Diagnostics belong on stderr, matching existing runtime error reporting.
- Log state is process-local and contains only readiness, attempted, a validated short reason code, and an observation timestamp. Invalid results and exceptions use fixed public reason codes.
- Repeated identical state tuples must not emit another line; no per-pass logging or additional file I/O is needed.
