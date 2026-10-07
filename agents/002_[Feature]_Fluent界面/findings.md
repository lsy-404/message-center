# Findings
- Published Fluent release 0.2.10 exports FluentTheme, FluentButton, FluentSwitch, and the Fluent token stylesheet under Apache-2.0.
- Package NOTICE includes Microsoft Fluent UI System Icons MIT attribution; both NOTICE and LICENSE are preserved and served under /vendor/fluent/.
- FluentTheme resolves system light/dark mode; app color aliases use Fluent tokens and retain fallback declarations for older Safari CSS support.
- Inbox polling remains paused in hidden tabs and refreshes on visibility/pageshow. Broad backdrop blur was removed.
- iPad mini 4 portrait uses 768 CSS pixels; the 820px breakpoint presents compact navigation. Build target is Safari 15.
- Playwright Chromium synthetic fixture verified message rendering, 768px layout without horizontal overflow, and thread open/back behavior. Playwright WebKit executable was unavailable, so direct Safari engine verification was not possible.
- Worker static asset path allowlist now includes the Fluent attribution directory; request authentication flow is unchanged.
