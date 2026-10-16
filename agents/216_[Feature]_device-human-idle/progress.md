# Progress

- Added resume cleanup signalling in `bridge/device-runtime/device_runtime.py`; the stable activity token is retained across adapter failures and cleared only by an exact cleanup-complete acknowledgement.
- Added a focused runtime regression test confirming failed calls retry with the same token and successful acknowledgement stops repeats.
- Injected inactive host monitors in runtime/outbox fixtures, keeping device-native monitor tests isolated.
- `python test/test_device_activity.py -v`: 15 tests passed; `python test/test_device_runtime.py -q`: 108 tests passed, 2 skipped; outbox batch tests: 10 passed.
