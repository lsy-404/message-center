# Findings
- Published Fluent release 0.2.10 exports FluentTheme, FluentButton, FluentSwitch, and the Fluent token stylesheet under Apache-2.0.
- Package NOTICE includes Microsoft Fluent UI System Icons MIT attribution; both NOTICE and LICENSE are preserved and served under /vendor/fluent/.
- FluentTheme resolves system light/dark mode; app color aliases use Fluent tokens and retain fallback declarations for older Safari CSS support.
- Inbox polling remains paused in hidden tabs and refreshes on visibility/pageshow. Broad backdrop blur was removed.
- iPad mini 4 portrait uses 768 CSS pixels; the 820px breakpoint presents compact navigation. Build target is Safari 15.
- Playwright Chromium synthetic fixture verified message rendering, 768px layout without horizontal overflow, and thread open/back behavior. Playwright WebKit executable was unavailable, so direct Safari engine verification was not possible.
- Worker static asset path allowlist now includes the Fluent attribution directory; request authentication flow is unchanged.

## Inbox refresh follow-up
- `setInterval` launched a new GET every five seconds even while an earlier request remained pending; revision filtering only stopped stale rendering and did not bound network or JSON work.
- Refresh should schedule the next attempt only after the current fetch settles, with exponential retry delay capped at one minute.
- Each inbox GET needs a bounded, independent AbortController. Session selection changes may abort that GET; send and upload POSTs must remain outside that cancellation path.
- Hidden/offline states suspend the refresh loop; visibility/pageshow/online recovery should trigger one immediate refresh.
- Implemented a timeout-bounded inbox GET gate. Switching conversations aborts the old GET, and only the active request for the current conversation may apply data; POST sends receive no inbox signal.
- Polling now waits for completion, retries failures at 10/20/40/60-second intervals, and can wake immediately after visibility/network recovery. Unchanged inbox rows are compared before replacing the Vue snapshot.
- Root `test/inbox-refresh.test.mjs` exercises slow-request single-flight, retry delay/cap, suspend/resume, and rapid-selection cancellation/stale-response guards.
- Validation passed: UI `pnpm run check` and `pnpm run build`; inbox refresh, Worker smoke, and Worker schema tests; `git diff --check`.
