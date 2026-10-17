# Structured quote receive replay

- [x] Compare the live pending event with the existing cloud UI record without exposing credentials or resending QQ messages.
- [x] Accept only exact quote-marker removal with an explicit valid reply and unchanged message envelope; preserve arbitrary body conflicts.
- [x] Carry quote metadata through background group normalization as well as ordinary events, with replayable partial-write recovery.
- [x] Add integration coverage for group/direct replay, wrong conversation/sender/time/body and partial progress.
- [ ] Review, validate and deploy scoped code; observe the real durable queue drain before claiming restored receive.
