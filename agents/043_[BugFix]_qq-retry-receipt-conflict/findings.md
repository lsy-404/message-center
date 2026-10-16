# Findings

- A QQ completion with `retry: true` currently chooses `pending` before inspecting successful or uncertain delivery evidence. A valid native receipt combined with retry can therefore requeue a send already proven delivered.
- The guard should be QQ-only and should preserve pending retries only when the completion explicitly carries no physical-send evidence.
- The Worker now maps retry plus success, uncertainty, dispatch, receipt, or external-ID evidence to `manual_review`. A retry with `dispatched: false` and no such evidence remains `pending`.
- Focused Node regression suite passes, including success/receipt, dispatched, uncertain, and no-dispatch retry cases.
