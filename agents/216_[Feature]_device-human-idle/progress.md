# Progress

- Added one-shot resume cleanup signalling in `bridge/device-runtime/device_runtime.py`; it is emitted only on the first QQ `ensure-active` adapter request after monitor state transitions from paused to idle.
- Added a focused runtime regression test confirming the signal is absent during ordinary requests and is not repeated on subsequent wake requests.
- `python test/test_device_activity.py -v`: 15 tests passed.
