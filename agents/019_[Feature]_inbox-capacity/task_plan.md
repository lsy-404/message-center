# Bounded inbox capacity

## Scope
- Raise the device source cursor conversation bound from 200 to 256 while preserving its 64 KiB cursor limit.
- Raise the Worker inbox conversation query bound to 512 while leaving message detail limits unchanged.
- Add bounded incremental conversation-list rendering and search across the entire returned conversation dataset.
- Add root `/test` regression coverage for 256/257 cursors, 512/513 inbox conversations, and finding a late conversation by search.

## Steps
- [x] Review existing Worker inbox SQL, Vue list patterns, and cursor tests.
- [x] Add pure bounded list filtering/paging utility and integrate Fluent-styled search/more controls.
- [x] Update cursor and Worker limits with focused tests.
- [x] Run focused tests, UI type check/build, and inspect the final diff for scope and identifiers.
- [x] Commit the local task branch without opening a PR.

## Constraints
- Keep messages query cap at 300 and cursor JSON cap at 64 KiB.
- Keep DOM rendering bounded; search must cover the full loaded inbox dataset.
- Preserve all existing untracked `work/` content; do not touch device/private/cloud deployment state.
