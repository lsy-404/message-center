# Task plan

- [x] Load repository and Workers workflow instructions and inspect both repository baselines.
- [x] Verify QQ event external-ID construction and Worker command completion/inbound behavior.
- [x] Add a validated native external ID to QQ completion results and carry it through the device runtime.
- [x] Bind receipt-first IDs to the queued outbound row and reconcile event-first self rows by exact external ID.
- [x] Add public Worker/SQLite tests for both orderings, duplicate completion, self-direction, and same-text distinct IDs.
- [x] Run focused public tests and inspect diff without pushing.
- [x] Commit the isolated public change.
