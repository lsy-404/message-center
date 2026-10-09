# Web send request-key persistence

## Goal

Reuse the Worker idempotency key when a send POST is retried after a browser reload or network error, so an accepted command whose response was lost is not queued again.

## Plan

- [x] Add a small browser helper that hashes the conversation and exact payload, then stores/reuses a random request ID without storing message text.
- [x] Keep the pending key before the POST and remove only that key after an accepted response includes durable message and command IDs.
- [x] Add root `/test` coverage for reload reuse, changed/reverted payloads, storage privacy, and acceptance/failure cleanup.
- [x] Run focused tests, UI type-check/build, inspect the diff, and commit the isolated branch for review.
- [ ] Root reviews the patch; do not deploy or push before review.

## Boundaries

- Do not change Worker idempotency or command lease behavior.
- Do not change draft or attachment storage UX.
- Do not deploy or push; wait for root review.
