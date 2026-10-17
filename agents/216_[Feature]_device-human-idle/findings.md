# Findings

- Activity state is version 4 and is accepted on restart only when it is a bounded regular non-symlink file with the complete typed schema.
- Missing, malformed, oversized, stale, or invalid state fails closed and requires the 180-second safety grace plus cleanup.
- Only an exact FileNotFoundError is treated as a first-run missing state; symlinks (including dangling links), non-regular files, and lookup/read errors preserve cleanup-required fail-closed behavior.
- A strict healthy/idle state with cleanupRequired false can restart through safety grace without consuming app-card cleanup budget.
- Actual physical HOME/touch and SpringBoard cleanup validation remain parent-owned.
- The checked-in classifier sees only callback-root events: type 11 immediately updates digitizer activity; type 3 is read for the verified consumer HOME usage/down fields. Apple OSS evidence for child ownership and CoreFoundation accessors is now documented below, but does not establish that the C child getter is exported or returns a CFArray on this iPad.
- A live snapshot with HOME sequence 1 and digitizer sequence 0 confirms HOME classification only. It does not establish whether touch reports were absent, wrapped in a root event, or missed by event delivery; no lastActivityAt timing sample was provided to determine the resume deadline.
- ActivityPolicy starts its 180-second timer when the monitor is ready, resets lastActivityAt on each classified HOME/digitizer callback, and clears armed only after the monotonic elapsed interval reaches 180 seconds. Later callbacks while cleanupRequired is already true stay in memory and the monitor persists them on its two-second heartbeat; no per-input timestamp history is kept.
- A bounded diagnostic should aggregate only callback-root event-type counts and, only after verified API evidence, child-event-type counts. Keep fixed-size counters and strict duration/event caps; emit a single aggregate summary, with no coordinates, keyboard usage/value fields, text, raw event dumps, or per-event logs.
- Before implementing child traversal, parent should supply the primary target header declaration, exact function ABI and return ownership/lifetime, and actual-device export evidence for the child enumerator. Device validation should compare aggregate root/child type counts during a bounded period containing one observed HOME and one touch, while separately checking monitor health and lastActivityAt before/after.
# HID child traversal evidence and probe boundary

Apple's current IOHIDFamily open-source `IOHIDEvent.h` declares the event-owned `_children` member as `OSArray *`, and exposes `OSArray *getChildren()`; `IOHIDEvent.cpp::free()` releases `_children` before freeing the event. This supports treating the child collection as borrowed and only using it while the callback's event is alive. The evidence does not establish that the target's C export `IOHIDEventGetChildren` exists or that it bridges to a CFArray. That exact export and ABI remain an explicit target-only validation gate; the diagnostic probe fails closed if the export is unavailable or unusable.

Apple's CoreFoundation implementation establishes `CFArrayGetCount(CFArrayRef) -> CFIndex` and `CFArrayGetValueAtIndex(CFArrayRef, CFIndex) -> const void *`; the latter returns the bucket's item directly without retaining it. On the 64-bit Darwin target, the probe uses `c_long` for `CFIndex` and opaque pointers for the array and event references. These calls are only used after root verifies the IOHID C export/bridge on the target.

Primary source evidence:

- [IOHIDEvent.h: event owns an OSArray child collection and declares getChildren](https://github.com/apple-oss-distributions/IOHIDFamily/blob/main/IOHIDFamily/IOHIDEvent.h#L2011-L2013)
- [IOHIDEvent.cpp: event free releases its child collection](https://github.com/apple-oss-distributions/IOHIDFamily/blob/main/IOHIDFamily/IOHIDEvent.cpp#L2354-L2381)
- [CFArray.c: CFArrayGetCount uses CFIndex](https://github.com/apple-oss-distributions/CF/blob/main/CFArray.c#L3118-L3128)
- [CFArray.c: CFArrayGetValueAtIndex returns the stored pointer](https://github.com/apple-oss-distributions/CF/blob/main/CFArray.c#L3183-L3195)

The top-level activity classifier currently only records digitizer activity for root type 11. Prior device counters (Home sequence 1, digitizer sequence 0) establish that Home was classified, but cannot establish whether the subsequent touch was absent, delivered in a non-digitizer root, wrapped in child events, or not delivered to this listener. A bounded aggregate probe now counts root event types and parent/child type pairs only, with a 30-second cap, 25,000 callback cap, depth 8, 128 nodes per callback, fixed 64-type counters, and no per-event output or payload/coordinate reads. Root must first validate the target export and then run the probe during a controlled physical touch window. No production event classification is changed by this investigation.

Timing remains uncertain: root reported a monotonic `lastActivityAt` and a later process uptime consistent with roughly two minutes from Home to that sample, but this does not identify the timestamp of the physical touch or prove that the digitizer counter failed to refresh. Collection may also remain paused due to the separate outbox condition root is investigating.
