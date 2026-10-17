# Findings

- The Darwin Relay constructor uses the default adapter lambda for `activity-mirror-path`; without a timeout mapping, startup raised `ValueError("unsupported_adapter_operation")` before the private adapter could run.
- The operation now uses a fixed five-second subprocess timeout. The regression patches only `run_adapter`, starts Darwin without injecting `adapter_call`, and asserts the exact request and timeout.
- Darwin bootstrap failures now classify as `activity_mirror_response_not_object`, `activity_mirror_response_fields_invalid`, `activity_mirror_adapter_rejected`, or `activity_mirror_path_invalid`; no raw adapter error or path is included in the raised error.
- No device or cloud access was used.
