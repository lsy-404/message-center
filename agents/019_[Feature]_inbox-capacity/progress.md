# Progress

- Confirmed worktree state and created `feature/inbox-capacity` from local `main`; preserved the pre-existing untracked `work/` directory.
- Audited the Fluent package: it has `FluentField` and `FluentButton`, but no conversation list or virtual-list component.
- Added 100-row fixed pagination and full-dataset title/preview/channel search to the inbox.
- Raised the device cursor bound to 256 and the Worker conversation list to 512; message and attachment query caps remain at 300.
- Added tests for 256 accepted / 257 rejected cursors, 513 Worker rows bounded to 512, tail-page/search behavior, and unchanged message query caps.
- Focused validation passed: cursor tests 9/9, capacity tests 2/2, existing large-group inbox test passed, Vue type check and Vite production build passed.
- The local task commit was merged into main, deployed, and verified. The inbox returns up to 512 conversations, renders 100 per page with search across the full loaded set, keeps the device cursor limit at 256, and leaves message detail queries capped at 300.
