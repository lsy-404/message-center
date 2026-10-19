# Findings

- Worker heartbeat previously converted every supplied state except offline to online. It now accepts only online/offline/degraded; omitted state remains online for existing callers, while invalid supplied state returns HTTP 400.
- Snapshot liveState now has a closed enum and fail-closes invalid stored values to offline. Existing freshness behavior is unchanged: stale online becomes offline; degraded remains degraded even with an old heartbeat.
- Worker command leasing has no separate online-only gate; UI send preflight now treats online and degraded as reachable and offline as unavailable, while capability and auth checks remain unchanged.
- UI connector and conversation state types are closed over the three states. Degraded is rendered as 部分同步 with existing warning tokens and counted separately from online.
- Host execution was blocked by missing worktree dependencies: worker smoke could not resolve openid-client; UI check/build could not find vue-tsc/vite because node_modules is absent. Static diff checks and syntax review remain available.