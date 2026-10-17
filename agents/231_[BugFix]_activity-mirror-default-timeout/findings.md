# Findings

- The Darwin Relay constructor uses the default adapter lambda for `activity-mirror-path`; without a timeout mapping, startup raised `ValueError("unsupported_adapter_operation")` before the private adapter could run.
- The operation now uses a fixed five-second subprocess timeout. The regression patches only `run_adapter`, starts Darwin without injecting `adapter_call`, and asserts the exact request and timeout.
- No device or cloud access was used.
