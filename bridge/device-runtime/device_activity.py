from __future__ import annotations

import ctypes
import json
import math
import os
import platform
import tempfile
import threading
import time
from typing import Any, Callable, Optional

IDLE_SECONDS = 180.0
MAX_STATE_BYTES = 1024
KEYBOARD_EVENT = 3
DIGITIZER_EVENT = 11
KEYBOARD_USAGE_PAGE_FIELD = KEYBOARD_EVENT << 16
KEYBOARD_USAGE_FIELD = KEYBOARD_USAGE_PAGE_FIELD + 1
KEYBOARD_DOWN_FIELD = KEYBOARD_USAGE_PAGE_FIELD + 2
CONSUMER_USAGE_PAGE = 0x0C
HOME_USAGE = 0x40


class ActivityStateError(RuntimeError):
    pass


def _atomic_state_write(path: str, armed: bool) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".device-activity-", dir=parent)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "armed": bool(armed)}, stream,
                      separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            parent_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_armed_state(path: str) -> Optional[bool]:
    try:
        with open(path, "r", encoding="utf-8") as stream:
            encoded = stream.read(MAX_STATE_BYTES + 1)
        if len(encoded.encode("utf-8")) > MAX_STATE_BYTES:
            return None
        raw = json.loads(encoded)
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if (not isinstance(raw, dict) or set(raw) != {"version", "armed"} or
            type(raw.get("version")) is not int or raw["version"] != 1 or
            type(raw.get("armed")) is not bool):
        return None
    return raw["armed"]


class ActivityPolicy:
    def __init__(self, state_path: str, *, idle_seconds: float = IDLE_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if (isinstance(idle_seconds, bool) or not isinstance(idle_seconds, (int, float))
                or not math.isfinite(float(idle_seconds)) or idle_seconds <= 0):
            raise ValueError("invalid_idle_seconds")
        self.state_path = os.fspath(state_path)
        self.idle_seconds = float(idle_seconds)
        self.clock = clock
        self._lock = threading.Lock()
        self._healthy = False
        self._failed = False
        self._armed = True
        self._last_activity_at: Optional[float] = None
        self._home_sequence = 0
        self._digitizer_sequence = 0
        self._persistence_pending = False
        self._state_generation = 0
        self._reason = "monitor_starting"

    def start_grace(self) -> bool:
        now = self.clock()
        saved_armed = _load_armed_state(self.state_path)
        with self._lock:
            self._armed = True
            self._last_activity_at = now
            self._home_sequence = 0
            self._healthy = False
            self._failed = False
            self._reason = "restart_pause" if saved_armed is True else "startup_grace"
            self._state_generation += 1
        try:
            _atomic_state_write(self.state_path, True)
        except Exception:
            self.fail("state_unavailable")
            return False
        return True

    def mark_ready(self) -> None:
        now = self.clock()
        with self._lock:
            if (self._failed or isinstance(now, bool) or
                    not isinstance(now, (int, float)) or
                    not math.isfinite(float(now)) or self._last_activity_at is None or
                    now < self._last_activity_at):
                self._healthy = False
                self._reason = "activity_state_unknown"
                return
            self._last_activity_at = now
            self._armed = True
            self._healthy = True
            if self._reason not in {"restart_pause", "human_activity"}:
                self._reason = "startup_grace"

    def fail(self, reason: str = "monitor_failed") -> None:
        with self._lock:
            self._healthy = False
            self._failed = True
            self._armed = True
            self._reason = reason
            self._persistence_pending = True
            self._state_generation += 1

    def record_activity(self, kind: str, at: Optional[float] = None) -> None:
        if kind not in {"home", "digitizer"}:
            return
        now = self.clock() if at is None else at
        with self._lock:
            if (isinstance(now, bool) or not isinstance(now, (int, float))
                    or self._last_activity_at is None or now < self._last_activity_at):
                self._healthy = False
                self._failed = True
                self._armed = True
                self._reason = "monotonic_clock_invalid"
                self._persistence_pending = True
                self._state_generation += 1
                return
            was_armed = self._armed
            self._armed = True
            self._last_activity_at = float(now)
            if kind == "home":
                self._home_sequence += 1
            elif kind == "digitizer":
                self._digitizer_sequence += 1
            self._reason = "human_activity"
            if not was_armed:
                self._persistence_pending = True
                self._state_generation += 1

    def flush_pending_state(self) -> bool:
        with self._lock:
            if not self._persistence_pending:
                return True
            armed = self._armed
            generation = self._state_generation
        try:
            _atomic_state_write(self.state_path, armed)
        except Exception:
            self.fail("state_unavailable")
            return False
        with self._lock:
            if generation == self._state_generation:
                self._persistence_pending = False
            if self._reason == "state_unavailable":
                self._healthy = False
                self._failed = True
                return False
            return not self._persistence_pending

    def snapshot(self) -> dict[str, Any]:
        now = self.clock()
        with self._lock:
            if (isinstance(now, bool) or not isinstance(now, (int, float)) or
                    not math.isfinite(float(now)) or self._last_activity_at is None or
                    now < self._last_activity_at):
                self._healthy = False
                self._failed = True
                self._armed = True
                self._reason = "monotonic_clock_invalid"
                self._persistence_pending = True
                self._state_generation += 1
            if (self._healthy and self._armed and not self._persistence_pending
                    and self._last_activity_at is not None
                    and now - self._last_activity_at >= self.idle_seconds):
                self._armed = False
                self._reason = "idle"
                self._persistence_pending = True
                self._state_generation += 1
            healthy = self._healthy and not self._persistence_pending
            armed = self._armed
            last_activity_at = self._last_activity_at
            home_sequence = self._home_sequence
            digitizer_sequence = self._digitizer_sequence
            reason = self._reason
        if self._persistence_pending:
            self.flush_pending_state()
            with self._lock:
                healthy = self._healthy and not self._persistence_pending
                armed = self._armed
                reason = self._reason
        idle_for = None if last_activity_at is None else max(0.0, now - last_activity_at)
        return {
            "healthy": healthy,
            "armed": armed,
            "shouldPause": (not healthy) or armed,
            "homeSequence": home_sequence,
            "digitizerSequence": digitizer_sequence,
            "lastActivityAt": last_activity_at,
            "idleFor": idle_for,
            "reason": reason,
        }


class InactiveHostMonitor:
    def start(self) -> None:
        return None

    def snapshot(self) -> dict[str, Any]:
        return {"healthy": True, "armed": False, "shouldPause": False,
                "homeSequence": 0, "lastActivityAt": None, "idleFor": None,
                "reason": "unsupported_host"}

    def stop(self) -> None:
        return None


class NativeActivityMonitor:
    def __init__(self, state_path: str, *, idle_seconds: float = IDLE_SECONDS,
                 clock: Callable[[], float] = time.monotonic,
                 iokit: Any = None, core_foundation: Any = None) -> None:
        self.policy = ActivityPolicy(state_path, idle_seconds=idle_seconds, clock=clock)
        self._iokit = iokit
        self._cf = core_foundation
        self._client = None
        self._run_loop = None
        self._mode = None
        self._callback = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        if not self.policy.start_grace():
            return
        self._thread = threading.Thread(target=self._run, name="device-activity-monitor",
                                        daemon=True)
        self._thread.start()

    def snapshot(self) -> dict[str, Any]:
        return self.policy.snapshot()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))

    def _load_libraries(self) -> tuple[Any, Any]:
        iokit = self._iokit or ctypes.CDLL(
            "/System/Library/Frameworks/IOKit.framework/IOKit")
        core_foundation = self._cf or ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        return iokit, core_foundation

    def _bind(self) -> tuple[Any, Any, Any]:
        iokit, cf = self._load_libraries()
        client_create = iokit.IOHIDEventSystemClientCreateWithType
        client_create.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        client_create.restype = ctypes.c_void_p
        register = iokit.IOHIDEventSystemClientRegisterEventCallback
        callback_type = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        register.argtypes = [ctypes.c_void_p, callback_type,
                             ctypes.c_void_p, ctypes.c_void_p]
        register.restype = None
        unregister = iokit.IOHIDEventSystemClientUnregisterEventCallback
        unregister.argtypes = [ctypes.c_void_p]
        unregister.restype = None
        schedule = iokit.IOHIDEventSystemClientScheduleWithRunLoop
        schedule.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        schedule.restype = None
        unschedule = iokit.IOHIDEventSystemClientUnscheduleWithRunLoop
        unschedule.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        unschedule.restype = None
        get_type = iokit.IOHIDEventGetType
        get_type.argtypes = [ctypes.c_void_p]
        get_type.restype = ctypes.c_uint32
        get_integer = iokit.IOHIDEventGetIntegerValue
        get_integer.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        get_integer.restype = ctypes.c_long
        run_loop_get_current = cf.CFRunLoopGetCurrent
        run_loop_get_current.argtypes = []
        run_loop_get_current.restype = ctypes.c_void_p
        run_in_mode = cf.CFRunLoopRunInMode
        run_in_mode.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_bool]
        run_in_mode.restype = ctypes.c_int32
        cf_release = cf.CFRelease
        cf_release.argtypes = [ctypes.c_void_p]
        cf_release.restype = None
        default_mode = ctypes.c_void_p.in_dll(cf, "kCFRunLoopDefaultMode").value
        if not default_mode:
            raise ActivityStateError("run_loop_mode_unavailable")
        return iokit, cf, callback_type

    def _consume_event(self, event: Any) -> None:
        if not event:
            raise ActivityStateError("null_hid_event")
        event_type = int(self._iokit.IOHIDEventGetType(event))
        if event_type == DIGITIZER_EVENT:
            self.policy.record_activity("digitizer")
            return
        if event_type != KEYBOARD_EVENT:
            return
        page = int(self._iokit.IOHIDEventGetIntegerValue(
            event, KEYBOARD_USAGE_PAGE_FIELD))
        usage = int(self._iokit.IOHIDEventGetIntegerValue(
            event, KEYBOARD_USAGE_FIELD))
        down = int(self._iokit.IOHIDEventGetIntegerValue(
            event, KEYBOARD_DOWN_FIELD))
        if page == CONSUMER_USAGE_PAGE and usage == HOME_USAGE and down == 1:
            self.policy.record_activity("home")

    def _run(self) -> None:
        scheduled = False
        registered = False
        try:
            iokit, cf, callback_type = self._bind()
            self._iokit = iokit
            self._cf = cf
            client = iokit.IOHIDEventSystemClientCreateWithType(None, 1, None)
            if not client:
                raise ActivityStateError("hid_client_unavailable")
            self._client = client
            self._run_loop = cf.CFRunLoopGetCurrent()
            if not self._run_loop:
                raise ActivityStateError("run_loop_unavailable")
            self._mode = ctypes.c_void_p.in_dll(cf, "kCFRunLoopDefaultMode").value
            if not self._mode:
                raise ActivityStateError("run_loop_mode_unavailable")

            def callback(_target: Any, _refcon: Any, _queue: Any, event: Any) -> None:
                try:
                    self._consume_event(event)
                except Exception:
                    self.policy.fail("event_callback_failed")

            self._callback = callback_type(callback)
            iokit.IOHIDEventSystemClientRegisterEventCallback(
                client, self._callback, None, None)
            registered = True
            iokit.IOHIDEventSystemClientScheduleWithRunLoop(
                client, self._run_loop, self._mode)
            scheduled = True
            self.policy.mark_ready()
            while not self._stop_event.is_set():
                result = cf.CFRunLoopRunInMode(self._mode, 1.0, False)
                self.policy.flush_pending_state()
                if result == 1:
                    raise ActivityStateError("run_loop_finished")
        except Exception:
            self.policy.fail("monitor_failed")
        finally:
            if self._client and self._iokit:
                if registered:
                    try:
                        self._iokit.IOHIDEventSystemClientUnregisterEventCallback(
                            self._client)
                    except Exception:
                        pass
                if scheduled:
                    try:
                        self._iokit.IOHIDEventSystemClientUnscheduleWithRunLoop(
                            self._client, self._run_loop, self._mode)
                    except Exception:
                        pass
                if self._cf:
                    try:
                        self._cf.CFRelease(self._client)
                    except Exception:
                        pass
            self._client = None
            self._run_loop = None
            self._mode = None
            self._callback = None


def create_monitor(state_path: str, *, idle_seconds: float = IDLE_SECONDS,
                   clock: Callable[[], float] = time.monotonic) -> Any:
    if platform.system() == "Darwin" or os.environ.get("DEVICE_ACTIVITY_MONITOR") == "1":
        return NativeActivityMonitor(state_path, idle_seconds=idle_seconds, clock=clock)
    return InactiveHostMonitor()
