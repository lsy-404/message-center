# Findings

- The runtime currently allows 90 seconds for an adapter send. The private sender's verified bounded end-to-end budget is being raised to 120 seconds; the public subprocess allowance needs 10 seconds to serialize/return the result.
- Only `ADAPTER_SEND_TIMEOUT` changes to 130 seconds. Worker command leasing, adapter dispatch behavior, and other operation timeouts remain unchanged.
