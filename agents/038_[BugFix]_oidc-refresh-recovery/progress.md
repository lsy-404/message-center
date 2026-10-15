# Progress

- Inspected the worker OIDC implementation, root routing, auth tests and fixture, existing project rules, and prior OIDC task summaries.
- Confirmed standards discrepancy (refresh response token optional) and destructive catch behavior for ambiguous failures. No live cloud state was accessed.
- Updated refresh-token handling, provider error classification, durable persistence for received rotation, lease quarantine, and browser/API terminal-session responses.
- Added regressions for omitted refresh tokens, 5xx/network ambiguity, introspection outage after rotation, terminal `invalid_grant`, late refresh/logout races, and HTML/API reauthentication behavior.
- Follow-up: added the 60-second probe window for rotated responses without `expires_in`, plus regressions for this path, transient HTML 503, terminal HTML admin-role loss, and stale terminal CAS behavior.
- Focused Node tests pass: 35/35. `git diff --check` is clean. No Cloudflare deployment or live mutation was performed.
