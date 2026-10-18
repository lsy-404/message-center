# Progress

Created the isolated worktree from the requested public base. Updated the workflow pin, README, provenance text, and contract test assertions. No device, cloud, CI, or production installation was used.
Host contract test: 10 passed; git diff --check passed. Downloaded asset hash matched the workflow pin. No device, cloud, CI, or production installation was used.

Integration: the exact branch SHA was built successfully in run 39156181129. Every downloaded artifact checksum and source provenance was verified. The official rootless server package and matching helper were installed together; server, agent and helper hashes match the staged release and the existing service plist is unchanged. All 54 production module slots, queues, cursor, native quarantine, configuration and wake budgets were preserved.

Both old and new runtime versions passed 30 sequential owned-process attach/create/load/result/unload/detach/close iterations. Old maximum unload/detach/close was 9/11/4 ms; new was 6/5/6 ms. These fixtures make no QQ SDK calls and do not prove QQ stability.

After a genuine full 180-second activity-monitor grace, normal QQ restart was denied by the retained recovery budget. The application still uses its prior process, so fresh-process QQ acceptance remains pending. The receiver was restored through a fresh interpreter with its standard startup grace. No test message was sent.
