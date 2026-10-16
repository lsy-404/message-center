# QQ query-gate recovery

## Objective
Classify only exact native query-gate evidence and recover a dedicated receiver after three consecutive same-process observations using existing cooldown and budget controls.

## Constraints
No device, cloud, send, cursor, outbox, or schema changes. Generic scan errors, helper exceptions, and malformed evidence must not enter the pending recovery path.
