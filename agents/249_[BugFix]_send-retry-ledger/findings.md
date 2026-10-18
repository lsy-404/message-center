# Findings

- The adapter retry branch only changes ledger state, leaving result null and retryable zero on a new command. This made live C diagnostics contradictory even while the Worker received retry outcomes. Persisting the exact public outcome and retryable flag makes the durable record match the existing retry contract; it does not create or expand retries.
