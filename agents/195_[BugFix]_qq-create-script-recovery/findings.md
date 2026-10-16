# Findings

- Existing attach recovery already requires three consecutive failures for the same PID, validates PID > 1, and applies the persisted five-minute cooldown. The new native failure shape can reuse this bounded path without changing its budget or cooldown.
- Source failure classification is strict and allowlisted; malformed metadata becomes an unclassified source failure and resets specialized streaks.
- The focused runtime test initially returned a failed activation because its adapter fixture returned a scan-failure response for `ensure-active`; correcting the fixture to return a valid readiness response made the new recovery assertion pass.
- The first Worker Node test run could not import `openid-client` because worktree dependencies were absent. Installing the locked Worker dependencies resolved the environment issue; all Worker Node tests passed afterward.
