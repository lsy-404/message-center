from __future__ import annotations

import ctypes
import json
import math
import os
import platform
import re
import secrets
import stat
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
STATE_VERSION = 4
HEARTBEAT_SECONDS = 2.0
SHARED_MIRROR_ALIAS = "/var/jb/var/mobile/Library/MessageCenterActivity/runtime.activity.json"
STATE_FIELDS = {
    "version", "monitorId", "runtimePid", "generation", "publishedAt",
    "healthy", "armed", "cleanupRequired", "lastActivityAt",
    "homeSequence", "digitizerSequence",
}


class ActivityStateError(RuntimeError):
    pass


def _atomic_state_write(path: str, state: dict[str, Any]) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".device-activity-", dir=parent)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, separators=(",", ":"))
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


def shared_mirror_state_path() -> str:
    """Resolve the fixed rootless shared path while preserving the trusted alias boundary."""
    jbroot = os.path.realpath("/var/jb")
    if (not jbroot.startswith("/private/preboot/") or
            jbroot == "/private/preboot/" or
            not re.fullmatch(r"/private/preboot/[^/]+(?:/[^/]+)*", jbroot)):
        raise ActivityStateError("mirror_root_invalid")
    resolved = os.path.realpath(SHARED_MIRROR_ALIAS)
    expected = jbroot.rstrip("/") + "/var/mobile/Library/MessageCenterActivity/runtime.activity.json"
    if resolved != expected:
        raise ActivityStateError("mirror_path_invalid")
    return resolved


def _open_mirror_parent(path: str) -> int:
    if os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise ActivityStateError("mirror_writer_not_root")
    if (not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY") or
            type(path) is not str or not path.startswith("/") or "\x00" in path or
            any(part in ("", ".", "..") for part in path.split("/")[1:])):
        raise ActivityStateError("mirror_path_invalid")
    components = path.split("/")[1:-1]
    if not components or components[-1] != "MessageCenterActivity":
        raise ActivityStateError("mirror_directory_invalid")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open("/", flags)
    try:
        for index, component in enumerate(components):
            created = False
            if index == len(components) - 1:
                try:
                    os.mkdir(component, mode=0o755, dir_fd=descriptor)
                    created = True
                except FileExistsError:
                    pass
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
            if created:
                if os.fstat(descriptor).st_uid != 0:
                    raise ActivityStateError("mirror_directory_owner_changed")
                os.fchmod(descriptor, 0o755)
                os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or
                stat.S_IMODE(metadata.st_mode) != 0o755):
            raise ActivityStateError("mirror_directory_invalid")
        result, descriptor = descriptor, -1
        return result
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _atomic_mirror_state_write(path: str, state: dict[str, Any]) -> None:
    parent_fd = _open_mirror_parent(path)
    basename = os.path.basename(path)
    descriptor = -1
    temporary = None
    try:
        try:
            existing = os.stat(basename, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and (
                not stat.S_ISREG(existing.st_mode) or existing.st_uid != 0 or
                stat.S_IMODE(existing.st_mode) != 0o644):
            raise ActivityStateError("mirror_file_invalid")
        temporary = ".runtime-activity-" + secrets.token_hex(16)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                             os.O_NOFOLLOW, 0o644, dir_fd=parent_fd)
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(state, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, basename, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        temporary = None
        published = os.stat(basename, dir_fd=parent_fd, follow_symlinks=False)
        if (not stat.S_ISREG(published.st_mode) or published.st_uid != 0 or
                stat.S_IMODE(published.st_mode) != 0o644):
            raise ActivityStateError("mirror_publish_invalid")
        os.fsync(parent_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)


def _load_saved_state(path: str) -> tuple[Optional[bool], Optional[bool]]:
    try:
        link_metadata = os.lstat(path)
    except FileNotFoundError:
        return None, None
    except Exception:
        return None, True
    if not stat.S_ISREG(link_metadata.st_mode):
        return None, True
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            metadata = os.fstat(descriptor)
            if (not stat.S_ISREG(metadata.st_mode) or
                    (metadata.st_dev, metadata.st_ino) !=
                    (link_metadata.st_dev, link_metadata.st_ino)):
                return None, True
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                encoded = stream.read(MAX_STATE_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if len(encoded) > MAX_STATE_BYTES:
            return None, True
        raw = json.loads(encoded.decode("utf-8"))
    except FileNotFoundError:
        return None, True
    except Exception:
        return None, True
    if not isinstance(raw, dict) or set(raw) != STATE_FIELDS:
        return None, True
    if (type(raw["version"]) is not int or raw["version"] != STATE_VERSION or
            type(raw["monitorId"]) is not str or
            not re.fullmatch(r"[0-9a-f]{32}", raw["monitorId"]) or
            isinstance(raw["runtimePid"], bool) or
            not isinstance(raw["runtimePid"], int) or raw["runtimePid"] <= 1 or
            isinstance(raw["generation"], bool) or
            not isinstance(raw["generation"], int) or raw["generation"] < 1 or
            type(raw["healthy"]) is not bool or type(raw["armed"]) is not bool or
            type(raw["cleanupRequired"]) is not bool):
        return None, True
    for key in ("publishedAt", "lastActivityAt"):
        value = raw[key]
        if (value is not None and
                (isinstance(value, bool) or not isinstance(value, (int, float)) or
                 not math.isfinite(float(value)))):
            return None, True
    if raw["publishedAt"] is None:
        return None, True
    for key in ("homeSequence", "digitizerSequence"):
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None, True
    return raw["armed"], raw["cleanupRequired"]


class ActivityPolicy:
    def __init__(self, state_path: str, *, readable_state_path: Optional[str] = None,
                 idle_seconds: float = IDLE_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if (isinstance(idle_seconds, bool) or not isinstance(idle_seconds, (int, float))
                or not math.isfinite(float(idle_seconds)) or idle_seconds <= 0):
            raise ValueError("invalid_idle_seconds")
        self.state_path = os.fspath(state_path)
        self.readable_state_path = (None if readable_state_path is None else
                                    os.fspath(readable_state_path))
        if self.readable_state_path == self.state_path:
            raise ValueError("mirror_must_be_separate_from_primary_state")
        self.monitor_id = secrets.token_hex(16)
        self.idle_seconds = float(idle_seconds)
        self.clock = clock
        self._lock = threading.Lock()
        self._persist_lock = threading.Lock()
        self._healthy = False
        self._failed = False
        self._armed = True
        self._cleanup_required = False
        self._last_activity_at: Optional[float] = None
        self._home_sequence = 0
        self._digitizer_sequence = 0
        self._persistence_pending = False
        self._state_generation = 0
        self._reason = "monitor_starting"
        self._last_persisted_at: Optional[float] = None
        self._persisted_generation = 0

    def _state_locked(self, published_at: float) -> dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "monitorId": self.monitor_id,
            "runtimePid": os.getpid(),
            "generation": self._persisted_generation + 1,
            "publishedAt": published_at,
            "healthy": self._healthy,
            "armed": self._armed,
            "cleanupRequired": self._cleanup_required,
            "lastActivityAt": self._last_activity_at,
            "homeSequence": self._home_sequence,
            "digitizerSequence": self._digitizer_sequence,
        }

    def _persist_current(self) -> bool:
        with self._persist_lock:
            now = self.clock()
            published_at = time.time()
            with self._lock:
                if (isinstance(now, bool) or not isinstance(now, (int, float)) or
                        not math.isfinite(float(now)) or not math.isfinite(published_at)):
                    self._healthy = False
                    self._failed = True
                    self._armed = True
                    self._cleanup_required = True
                    self._reason = "clock_invalid"
                    return False
                state = self._state_locked(published_at)
                generation = self._state_generation
            try:
                _atomic_state_write(self.state_path, state)
            except Exception:
                self.fail("state_unavailable", persist=False)
                return False
            if self.readable_state_path is not None:
                try:
                    _atomic_mirror_state_write(self.readable_state_path, state)
                except Exception:
                    with self._lock:
                        self._healthy = False
                        self._failed = True
                        self._armed = True
                        self._cleanup_required = True
                        self._reason = "mirror_state_unavailable"
                        self._persistence_pending = True
                        self._state_generation += 1
                        failed_state = self._state_locked(time.time())
                    try:
                        _atomic_state_write(self.state_path, failed_state)
                        self._persisted_generation += 1
                    except Exception:
                        pass
                    try:
                        _atomic_mirror_state_write(self.readable_state_path, failed_state)
                    except Exception:
                        pass
                    return False
            with self._lock:
                self._persisted_generation += 1
                self._last_persisted_at = float(now)
                if generation == self._state_generation:
                    self._persistence_pending = False
                return not self._persistence_pending

    def start_grace(self) -> bool:
        now = self.clock()
        saved_armed, saved_cleanup = _load_saved_state(self.state_path)
        with self._lock:
            self._armed = True
            self._cleanup_required = (
                saved_cleanup if saved_cleanup is not None else
                saved_armed is True)
            self._last_activity_at = now
            self._home_sequence = 0
            self._healthy = False
            self._failed = False
            self._reason = "restart_pause" if self._cleanup_required else "startup_grace"
            self._state_generation += 1
        try:
            if not self._persist_current():
                return False
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
            self._state_generation += 1
            self._persistence_pending = True
        self._persist_current()

    def fail(self, reason: str = "monitor_failed", *, persist: bool = True) -> None:
        with self._lock:
            self._healthy = False
            self._failed = True
            self._armed = True
            self._cleanup_required = True
            self._reason = reason
            self._persistence_pending = True
            self._state_generation += 1
        if persist:
            self._persist_current()

    def record_activity(self, kind: str, at: Optional[float] = None) -> None:
        if kind not in {"home", "digitizer"}:
            return
        now = self.clock() if at is None else at
        with self._lock:
            if (isinstance(now, bool) or not isinstance(now, (int, float))
                    or not math.isfinite(float(now))
                    or self._last_activity_at is None or now < self._last_activity_at):
                self._healthy = False
                self._failed = True
                self._armed = True
                self._cleanup_required = True
                self._reason = "monotonic_clock_invalid"
                self._persistence_pending = True
                self._state_generation += 1
                return
            was_cleanup_required = self._cleanup_required
            self._armed = True
            self._cleanup_required = True
            self._last_activity_at = float(now)
            if kind == "home":
                self._home_sequence += 1
            elif kind == "digitizer":
                self._digitizer_sequence += 1
            self._reason = "human_activity"
            if not was_cleanup_required:
                self._persistence_pending = True
                self._state_generation += 1
        if not was_cleanup_required:
            self._persist_current()

    def stop(self) -> None:
        with self._lock:
            self._healthy = False
            self._failed = True
            self._reason = "monitor_stopped"
            self._persistence_pending = True
            self._state_generation += 1
        self._persist_current()

    def acknowledge_cleanup(self, token: str) -> bool:
        with self._lock:
            expected = "{}:{}:{}:{}".format(
                self.monitor_id, os.getpid(), self._home_sequence,
                self._digitizer_sequence)
            if (token != expected or self._armed or not self._healthy or
                    not self._cleanup_required):
                return False
            self._cleanup_required = False
            self._reason = "idle"
            self._state_generation += 1
            self._persistence_pending = True
        return self._persist_current()

    def heartbeat(self) -> bool:
        now = self.clock()
        with self._lock:
            if (self._last_persisted_at is not None and
                    now - self._last_persisted_at < HEARTBEAT_SECONDS and
                    not self._persistence_pending):
                return True
        return self._persist_current()

    def flush_pending_state(self) -> bool:
        with self._lock:
            if not self._persistence_pending:
                return True
        return self._persist_current()

    def snapshot(self) -> dict[str, Any]:
        now = self.clock()
        with self._lock:
            if (isinstance(now, bool) or not isinstance(now, (int, float)) or
                    not math.isfinite(float(now)) or self._last_activity_at is None or
                    now < self._last_activity_at):
                self._healthy = False
                self._failed = True
                self._armed = True
                self._cleanup_required = True
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
            cleanup_required = self._cleanup_required
            last_activity_at = self._last_activity_at
            home_sequence = self._home_sequence
            digitizer_sequence = self._digitizer_sequence
            reason = self._reason
        if self._persistence_pending:
            self.flush_pending_state()
            with self._lock:
                healthy = self._healthy and not self._persistence_pending
                armed = self._armed
                cleanup_required = self._cleanup_required
                reason = self._reason
        idle_for = None if last_activity_at is None else max(0.0, now - last_activity_at)
        return {
            "healthy": healthy,
            "armed": armed,
            "cleanupRequired": cleanup_required,
            "shouldPause": (not healthy) or armed,
            "homeSequence": home_sequence,
            "digitizerSequence": digitizer_sequence,
            "lastActivityAt": last_activity_at,
            "idleFor": idle_for,
            "reason": reason,
            "monitorId": self.monitor_id,
            "runtimePid": os.getpid(),
        }

class InactiveHostMonitor:
    def start(self) -> None:
        return None

    def snapshot(self) -> dict[str, Any]:
        return {"healthy": True, "armed": False, "shouldPause": False,
                "cleanupRequired": False,
                "homeSequence": 0, "lastActivityAt": None, "idleFor": None,
                "reason": "unsupported_host", "monitorId": None}

    def stop(self) -> None:
        return None


class NativeActivityMonitor:
    def __init__(self, state_path: str, *, readable_state_path: Optional[str] = None,
                 idle_seconds: float = IDLE_SECONDS,
                 clock: Callable[[], float] = time.monotonic,
                 iokit: Any = None, core_foundation: Any = None) -> None:
        self.policy = ActivityPolicy(state_path, readable_state_path=readable_state_path,
                                     idle_seconds=idle_seconds, clock=clock)
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

    def request_fields(self) -> dict[str, Any]:
        state = self.policy.snapshot()
        return {
            "activityStatePath": (self.policy.readable_state_path or
                                  self.policy.state_path),
            "activityMonitorId": self.policy.monitor_id,
            "activityRuntimePid": os.getpid(),
            "activityResumeToken": "{}:{}:{}:{}".format(
                self.policy.monitor_id, os.getpid(), state["homeSequence"],
                state["digitizerSequence"]),
        }

    def acknowledge_cleanup(self, token: str) -> bool:
        return self.policy.acknowledge_cleanup(token)

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        self.policy.stop()
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
                self.policy.heartbeat()
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


def create_monitor(state_path: str, *, readable_state_path: Optional[str] = None,
                   idle_seconds: float = IDLE_SECONDS,
                   clock: Callable[[], float] = time.monotonic) -> Any:
    if platform.system() == "Darwin" or os.environ.get("DEVICE_ACTIVITY_MONITOR") == "1":
        return NativeActivityMonitor(state_path, readable_state_path=readable_state_path,
                                     idle_seconds=idle_seconds, clock=clock)
    return InactiveHostMonitor()
