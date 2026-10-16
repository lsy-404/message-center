# Findings

Review target: public commit `d42e01ad8089e5ad17c2480b301a9c776178b2cb`, branch `feature/qq-group-helper-ui`, based on `main` `3caeb95`.

## Candidate review

- `/api/inbox` projects `connector_kind` into `connectorKind` and returns `conversationType`, `placement`, and `unreadCount`; the candidate's classification uses the protocol field `connectorKind === 'qq'`, not a display label. This preserves custom QQ channel labels.
- The group-assistant predicate is strict: QQ + `conversationType === 'group'` + placement `folded` or `message_box`. It excludes normal QQ groups, direct QQ chats, unknown placements, and non-QQ groups.
- Search and unread filtering compose with that predicate, and the displayed list drives pagination, range/count labels, and visible rows. The QQ protocol filter is separately available; the “return to QQ” action selects it. Existing `FluentButton` and `FluentField` components are reused, and rendering remains page-limited through the existing 100-item page helper.
- Blocker in candidate `App.vue:828-835`: when `showQQGroups()` finds no eligible conversation in the current search/unread-filtered list, it does not clear or replace the prior `selectedId`, messages, or composer. Since the thread and send action still derive from that selection, opening an empty assistant view from another connector can leave the previous recipient active. `selectFilter()` already clears that state for an empty list; the new route needs equivalent behavior. The candidate also leaves `activeFilter` unchanged on entry; root requested entry to establish the QQ protocol filter.
- Navigation order currently appends the QQ filter after all non-QQ channel labels. Root requested that the QQ filter precede WeChat, so this needs an ordering assertion in the final candidate.
- Validation on exact candidate `d42e01ad8089e5ad17c2480b301a9c776178b2cb`: targeted Node helper tests passed 4/4; `pnpm --dir cloudflare-worker/ui check` and `pnpm --dir cloudflare-worker/ui build` passed. These do not exercise Vue selection/send state in a browser. No browser, cloud write, or device operation was performed.
