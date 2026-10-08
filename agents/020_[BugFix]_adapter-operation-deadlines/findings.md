# Findings

- A scan wraps process lookup (up to 5 seconds) and native-helper execution (up to 28 seconds) inside a 30-second runtime adapter subprocess deadline. This can terminate the adapter process group before it returns.
- QQ send performs three serialized native helper stages, so it needs a larger fixed deadline than a scan.
- Keep operation budgets in code rather than configuration; an adapter timeout after command leasing must remain an uncertain, non-retryable send result.
