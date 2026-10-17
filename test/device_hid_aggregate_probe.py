"""Bounded, type-only IOHID event-tree probe for explicit device validation."""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

TYPE_LIMIT = 64
MAX_DURATION_SECONDS = 300.0
MAX_EVENTS = 25000
MAX_CHILDREN_PER_EVENT = 32
MAX_TREE_DEPTH = 4
MAX_TREE_NODES = 64


class Aggregates:
    def __init__(self) -> None:
        self.root_types = [0] * TYPE_LIMIT
        self.child_types = [0] * TYPE_LIMIT
        self.unknown_root_types = 0
        self.unknown_child_types = 0
        self.child_traversal_errors = 0
        self.events = 0

    def add(self, root_event: int, get_type: Callable[[int], int],
            get_children: Callable[[int], int] | None = None,
            array_count: Callable[[int], int] | None = None,
            array_value: Callable[[int, int], int] | None = None,
            cf_type_id: Callable[[int], int] | None = None,
            cf_array_type_id: int | None = None) -> None:
        self.events += 1
        root_type = int(get_type(root_event))
        if 0 <= root_type < TYPE_LIMIT:
            self.root_types[root_type] += 1
        else:
            self.unknown_root_types += 1

        if get_children is None:
            return
        try:
            if any(value is None for value in
                   (array_count, array_value, cf_type_id, cf_array_type_id)):
                raise ValueError("incomplete_child_api")
            local_types, local_unknown = _collect_child_types(
                root_event, get_type, get_children, array_count, array_value,
                cf_type_id, cf_array_type_id)
            for event_type, count in local_types.items():
                self.child_types[event_type] += count
            self.unknown_child_types += local_unknown
        except Exception:
            self.child_traversal_errors += 1

    def summary(self, elapsed: float, callback_errors: int) -> dict:
        return {
            "elapsedSeconds": round(elapsed, 3),
            "events": self.events,
            "rootTypes": {str(i): count for i, count in enumerate(self.root_types) if count},
            "childTypes": {str(i): count for i, count in enumerate(self.child_types) if count},
            "unknownRootTypes": self.unknown_root_types,
            "unknownChildTypes": self.unknown_child_types,
            "childTraversalErrors": self.child_traversal_errors,
            "callbackErrors": callback_errors,
        }


def _collect_child_types(root_event: int, get_type: Callable[[int], int],
                         get_children: Callable[[int], int],
                         array_count: Callable[[int], int],
                         array_value: Callable[[int, int], int],
                         cf_type_id: Callable[[int], int],
                         cf_array_type_id: int) -> tuple[dict[int, int], int]:
    local_types: dict[int, int] = {}
    unknown = 0
    visited = 1

    def visit(event: int, depth: int) -> None:
        nonlocal visited, unknown
        child_array = int(get_children(event) or 0)
        if not child_array:
            return
        if int(cf_type_id(child_array)) != cf_array_type_id:
            raise ValueError("children_not_cfarray")
        count = int(array_count(child_array))
        if count < 0 or count > MAX_CHILDREN_PER_EVENT:
            raise ValueError("child_count_limit")
        if count and depth >= MAX_TREE_DEPTH:
            raise ValueError("child_depth_limit")
        if visited + count > MAX_TREE_NODES:
            raise ValueError("child_node_limit")
        for index in range(count):
            child = int(array_value(child_array, index) or 0)
            if not child:
                raise ValueError("null_child_event")
            visited += 1
            event_type = int(get_type(child))
            if 0 <= event_type < TYPE_LIMIT:
                local_types[event_type] = local_types.get(event_type, 0) + 1
            else:
                unknown += 1
            visit(child, depth + 1)

    visit(root_event, 0)
    return local_types, unknown

def _status_payload(aggregates: Aggregates, *, ready: bool, running: bool,
                    started_at: float | None, ended_at: float | None,
                    callback_errors: int, callback_limit_reached: bool,
                    teardown_errors: list[str]) -> dict:
    now = time.time()
    elapsed = 0.0 if started_at is None else max(0.0, now - started_at)
    payload = {
        "ready": ready,
        "running": running,
        "startedAt": started_at,
        "endedAt": ended_at,
        **aggregates.summary(elapsed, callback_errors),
        "callbackLimitReached": callback_limit_reached,
        "teardownErrors": list(teardown_errors),
    }
    return payload


def _atomic_write_status(path: str | os.PathLike[str], payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=target.parent,
                prefix=f".{target.name}.", suffix=".tmp", delete=False) as stream:
            temp_name = stream.name
            json.dump(payload, stream, separators=(",", ":"), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        if temp_name is not None and os.path.exists(temp_name):
            os.unlink(temp_name)


def run_probe(duration: float = 300.0, max_events: int = MAX_EVENTS,
              status_file: str | os.PathLike[str] | None = None) -> dict:
    if (isinstance(duration, bool) or not isinstance(duration, (int, float)) or
            not math.isfinite(float(duration)) or not 0 < duration <= MAX_DURATION_SECONDS):
        raise ValueError("duration must be within 0..300 seconds")
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
    libsystem = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    dlsym = libsystem.dlsym
    dlsym.argtypes, dlsym.restype = [void_p, ctypes.c_char_p], void_p
    get_children_symbol = dlsym(io._handle, b"IOHIDEventGetChildren")
    if not get_children_symbol:
        raise RuntimeError("hid_event_children_export_unavailable")
    get_children = ctypes.CFUNCTYPE(void_p, void_p)(get_children_symbol)
    cf_get_type_id = cf.CFGetTypeID
    cf_get_type_id.argtypes, cf_get_type_id.restype = [void_p], ctypes.c_ulong
    cf_array_get_type_id = cf.CFArrayGetTypeID
    cf_array_get_type_id.argtypes, cf_array_get_type_id.restype = [], ctypes.c_ulong
    cf_array_get_count = cf.CFArrayGetCount
    cf_array_get_count.argtypes, cf_array_get_count.restype = [void_p], ctypes.c_long
    cf_array_get_value = cf.CFArrayGetValueAtIndex
    cf_array_get_value.argtypes, cf_array_get_value.restype = [void_p, ctypes.c_long], void_p
    cf_array_type_id = int(cf_array_get_type_id())
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
    started_wall = None
    result = None
    teardown_errors = []

    def on_event(_target, _refcon, _queue, event):
        nonlocal callback_errors, callback_limit_reached
        if aggregates.events >= max_events:
            callback_limit_reached = True
            return
        try:
            aggregates.add(int(event), lambda ptr: int(get_type(ptr)),
                           lambda ptr: int(get_children(ptr) or 0),
                           lambda array: int(cf_array_get_count(array)),
                           lambda array, index: int(cf_array_get_value(array, index) or 0),
                           lambda array: int(cf_get_type_id(array)), cf_array_type_id)
            if aggregates.events >= max_events:
                callback_limit_reached = True
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
        started_wall = time.time()
        if status_file is not None:
            _atomic_write_status(status_file, _status_payload(
                aggregates, ready=True, running=True, started_at=started_wall,
                ended_at=None, callback_errors=callback_errors,
                callback_limit_reached=callback_limit_reached,
                teardown_errors=teardown_errors))
        deadline = started + float(duration)
        next_publish = time.monotonic() + 1.0
        while time.monotonic() < deadline and aggregates.events < max_events:
            remaining = max(0.0, deadline - time.monotonic())
            until_publish = max(0.0, next_publish - time.monotonic())
            status = int(run_in_mode(mode, min(1.0, remaining, until_publish or 0.001), False))
            if status == 1:
                raise RuntimeError("run_loop_finished")
            if status_file is not None and time.monotonic() >= next_publish:
                _atomic_write_status(status_file, _status_payload(
                    aggregates, ready=True, running=True, started_at=started_wall,
                    ended_at=None, callback_errors=callback_errors,
                    callback_limit_reached=callback_limit_reached,
                    teardown_errors=teardown_errors))
                next_publish = time.monotonic() + 1.0
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
        if status_file is not None:
            _atomic_write_status(status_file, _status_payload(
                aggregates, ready=started_wall is not None, running=False,
                started_at=started_wall, ended_at=time.time(),
                callback_errors=callback_errors,
                callback_limit_reached=callback_limit_reached,
                teardown_errors=teardown_errors))
        callback = None


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate IOHID callback root event types only")
    parser.add_argument("--seconds", type=float, default=300.0)
    parser.add_argument("--max-events", type=int, default=MAX_EVENTS)
    parser.add_argument("--status-file", required=True,
                        help="caller-owned path for atomic one-second aggregate status")
    args = parser.parse_args()
    try:
        print(json.dumps(run_probe(args.seconds, args.max_events, args.status_file), separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({"ready": False, "error": type(exc).__name__ + ":" + str(exc)}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
