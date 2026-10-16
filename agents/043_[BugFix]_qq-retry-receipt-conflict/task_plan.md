# QQ Retry and Receipt Conflict

- [x] Inspect completion payload fields and current QQ state precedence.
- [x] Make contradictory retry plus physical-send evidence terminal `manual_review` for QQ.
- [x] Add regression coverage for valid receipt, dispatched/uncertain evidence, and a genuine no-dispatch retry.
- [x] Run the focused Worker test, review the diff, and commit the scoped change.
