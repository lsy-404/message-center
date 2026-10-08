# Outbox delivery heartbeat progress

## Goal

During a bounded pass, report a connector heartbeat as online when this pass actually receives an acknowledged outbox delivery for that connector, even if its source scan is stale or unhealthy. Preserve source health, scan timestamps, source eligibility, and command polling gates.

## Scope

- `bridge/device-runtime/device_runtime.py`
- `test/test_device_runtime.py`
- This task's audit files and task index entry.

## Verification

- An unhealthy source with acknowledged delivery reports online, while command polling remains gated.
- Failed/no-ack delivery does not count as progress.
- Only the connector whose row was acknowledged gains online progress in a multi-connector pass.
- Run targeted device runtime tests and the full repository-root test suite.

## Limits

No device, cloud, deployment, credential, or private-adapter operations.
