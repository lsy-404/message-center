# Progress

- Reviewed the live issuer, OIDC identity mapping, encrypted token envelope, discovery cache, and private deployment config.
- Updated the ignored private deployment config issuer and current project instructions; retained the generic public deployment template.
- Existing OIDC suite passed 31 tests covering login, issuer validation, token envelope binding, refresh and logout.
- Production configuration now points to the personal issuer. All 11 bindings and deployed executable modules remain unchanged. Active version: b5a83f8b-6623-4b52-ac19-f0312fe15841.
- Live GET /login returns a redirect to id.leisiyu.dev/oauth/authorize. A Python default user-agent received an edge 403; curl returned the real application redirect.
- GitHub main reports protected=false. The primary worktree's four untracked files remain untouched.
