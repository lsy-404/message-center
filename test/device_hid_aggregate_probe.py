"""Bounded, aggregate-only IOHID event tree probe for explicit device validation."""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import sys
import time
from typing import Callable

TYPE_LIMIT = 64
MAX_DEPTH = 8
MAX_NODES_PER_EVENT = 128
MAX_DURATION_SECONDS = 30.0
MAX_EVENTS = 25000


class Aggregates:
    def __init__(self) -> None:
        self.root_types = [0] * TYPE_LIMIT
        self.child_types = [[0] * TYPE_LIMIT for _ in range(TYPE_LIMIT)]
        self.unknown_root_types = 0
        self.unknown_child_pairs = 0
        self.events = 0
        self.nodes = 0
        self.truncated_events = 0

    def add(self, root_event: int, get_type: Callable[[int], int],
            get_children: Callable[[int], list[int]]) -> None:
        self.events += 1
        root_type = int(get_type(root_event))
        if 0 <= root_type < TYPE_LIMIT:
            self.root_types[root_type] += 1
        else:
            self.unknown_root_types += 1
        visited = {root_event}
        self.nodes += 1
        edge_count = 0
        truncated = False
        stack = [(root_event, root_type, 0)]
        while stack:
            parent, parent_type, depth = stack.pop()
            if depth >= MAX_DEPTH:
                if get_children(parent):
                    truncated = True
                continue
            for child in get_children(parent):
                edge_count += 1
                if edge_count >= MAX_NODES_PER_EVENT or child in visited:
                    truncated = True
                    continue
                visited.add(child)
                self.nodes += 1
                child_type = int(get_type(child))
                if 0 <= parent_type < TYPE_LIMIT and 0 <= child_type < TYPE_LIMIT:
                    self.child_types[parent_type][child_type] += 1
                else:
                    self.unknown_child_pairs += 1
                stack.append((child, child_type, depth + 1))
        if truncated:
            self.truncated_events += 1

    def summary(self, elapsed: float, callback_errors: int) -> dict:
        return {
            "elapsedSeconds": round(elapsed, 3),
            "events": self.events,
            "nodes": self.nodes,
            "rootTypes": {str(i): count for i, count in enumerate(self.root_types) if count},
            "childTypePairs": [
                {"parentType": parent, "childType": child, "count": count}
                for parent, row in enumerate(self.child_types)
                for child, count in enumerate(row) if count
            ],
            "unknownRootTypes": self.unknown_root_types,
            "unknownChildPairs": self.unknown_child_pairs,
            "truncatedEvents": self.truncated_events,
            "callbackErrors": callback_errors,
        }


def run_probe(duration: float = 30.0, max_events: int = MAX_EVENTS) -> dict:
    if (isinstance(duration, bool) or not isinstance(duration, (int, float)) or
            not math.isfinite(float(duration)) or not 0 < duration <= MAX_DURATION_SECONDS):
        raise ValueError("duration must be within 0..30 seconds")
    if isinstance(max_events, bool) or not isinstance(max_events, int) or not 1 <= max_events <= MAX_EVENTS:
        raise ValueError("max_events must be within 1..25000")
    if sys.platform != "darwin":
        raise RuntimeError("device-only probe requires Darwin")

    io = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
    cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    void_p = ctypes.c_void_p

    create = io.IOHIDEventSystemClientCreateWithType
    create.argtypes, create.restype = [void_p, ctypes.c_int, void_p], void_p
    register = io.IOHIDEventSystemClientRegisterEventCallback
    callback_type = ctypes.CFUNCTYPE(None, void_p, void_p, void_p, void_p)
    register.argtypes, register.restype = [void_p, callback_type, void_p, void_p], None
    unregister = io.IOHIDEventSystemClientUnregisterEventCallback
    unregister.argtypes, unregister.restype = [void_p], None
    schedule = io.IOHIDEventSystemClientScheduleWithRunLoop
    schedule.argtypes, schedule.restype = [void_p, void_p, void_p], None
    unschedule = io.IOHIDEventSystemClientUnscheduleWithRunLoop
    unschedule.argtypes, unschedule.restype = [void_p, void_p, void_p], None

    get_type = io.IOHIDEventGetType
    get_type.argtypes, get_type.restype = [void_p], ctypes.c_uint32
    # This C export is checked on the target device before interpreting results.
    get_children = io.IOHIDEventGetChildren
    get_children.argtypes, get_children.restype = [void_p], void_p
    array_count = cf.CFArrayGetCount
    array_count.argtypes, array_count.restype = [void_p], ctypes.c_long
    array_value = cf.CFArrayGetValueAtIndex
    array_value.argtypes, array_value.restype = [void_p, ctypes.c_long], void_p

    run_loop_current = cf.CFRunLoopGetCurrent
    run_loop_current.argtypes, run_loop_current.restype = [], void_p
    run_in_mode = cf.CFRunLoopRunInMode
    run_in_mode.argtypes, run_in_mode.restype = [void_p, ctypes.c_double, ctypes.c_bool], ctypes.c_int32
    release = cf.CFRelease
    release.argtypes, release.restype = [void_p], None
    mode = void_p.in_dll(cf, "kCFRunLoopDefaultMode").value

    aggregates = Aggregates()
    callback_errors = 0
    callback_limit_reached = False
    client = None
    loop = None
    callback = None
    registered = False
    scheduled = False
    started = time.monotonic()
    result = None
    teardown_errors = []

    def children(event: int) -> list[int]:
        array = get_children(event)
        if not array:
            return []
        count = int(array_count(array))
        if count < 0 or count > MAX_NODES_PER_EVENT:
            raise RuntimeError("child_array_out_of_bounds")
        return [int(array_value(array, index)) for index in range(count)]

    def on_event(_target, _refcon, _queue, event):
        nonlocal callback_errors, callback_limit_reached
        if aggregates.events >= max_events:
            callback_limit_reached = True
            return
        try:
            aggregates.add(int(event), lambda ptr: int(get_type(ptr)), children)
        except Exception:
            callback_errors += 1

    try:
        client = create(None, 1, None)
        if not client or not mode:
            raise RuntimeError("hid_client_or_runloop_mode_unavailable")
        loop = run_loop_current()
        if not loop:
            raise RuntimeError("run_loop_unavailable")
        callback = callback_type(on_event)
        register(client, callback, None, None)
        registered = True
        schedule(client, loop, mode)
        scheduled = True
        deadline = started + float(duration)
        while time.monotonic() < deadline and aggregates.events < max_events:
            status = int(run_in_mode(mode, min(0.25, max(0.0, deadline - time.monotonic())), False))
            if status == 1:
                raise RuntimeError("run_loop_finished")
        elapsed = time.monotonic() - started
        result = aggregates.summary(elapsed, callback_errors)
        result["callbackLimitReached"] = callback_limit_reached
        result["ready"] = True
        return result
    finally:
        if client:
            if registered:
                try:
                    unregister(client)
                except Exception:
                    teardown_errors.append("unregister")
            if scheduled:
                try:
                    unschedule(client, loop, mode)
                except Exception:
                    teardown_errors.append("unschedule")
            try:
                release(client)
            except Exception:
                teardown_errors.append("release")
        if result is not None:
            result["teardownErrors"] = teardown_errors
        callback = None


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate IOHID event and child event types only")
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--max-events", type=int, default=MAX_EVENTS)
    args = parser.parse_args()
    try:
        print(json.dumps(run_probe(args.seconds, args.max_events), separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({"ready": False, "error": type(exc).__name__ + ":" + str(exc)}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
