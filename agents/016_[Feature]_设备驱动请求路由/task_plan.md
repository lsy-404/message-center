# Task Plan: Device Driver Request Routing

- [x] Inspect runtime scan/send request construction and private adapter driver/send contracts.
- [x] Add explicit connector-kind driver fields to runtime scan and authorized command requests.
- [x] Require canonical profile-prefixed conversation IDs and explicit authorization in the private adapter.
- [x] Preserve QQ scan/media behavior, keep WeChat send disabled, and map uncertain send results as non-retryable.
- [x] Add runtime and private adapter integration tests without using the shared temporary test file.
- [x] Run targeted suites and record the final request/response contract.
