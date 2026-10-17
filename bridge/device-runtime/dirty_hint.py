"""Generic local vnode hints for requesting an ordinary source scan."""

import os
import platform
import select
import stat
import sys
import time


MAX_WATCHED_PATHS = 3
RECONCILE_SECONDS = 1.0
DEBOUNCE_SECONDS = 1.0
MIN_SCAN_INTERVAL = 5.0
MIN_WAKE_INTERVAL = 5.0
DARWIN_O_EVTONLY = 0x00008000
NOTE_DELETE = 0x00000001
NOTE_WRITE = 0x00000002
NOTE_EXTEND = 0x00000004
NOTE_RENAME = 0x00000020
NOTE_REVOKE = 0x00000040
VNODE_FFLAGS = NOTE_DELETE | NOTE_WRITE | NOTE_EXTEND | NOTE_RENAME | NOTE_REVOKE


def _darwin_vnode_api():
    if sys.platform not in ("darwin", "ios") or platform.system() != "Darwin":
        return None
    required = (
        "kqueue", "kevent", "KQ_FILTER_VNODE", "KQ_EV_ADD", "KQ_EV_CLEAR",
        "KQ_NOTE_DELETE", "KQ_NOTE_WRITE", "KQ_NOTE_EXTEND", "KQ_NOTE_RENAME",
        "KQ_NOTE_REVOKE",
    )
    if any(not hasattr(select, name) for name in required):
        return None
    if (select.KQ_NOTE_DELETE, select.KQ_NOTE_WRITE, select.KQ_NOTE_EXTEND,
            select.KQ_NOTE_RENAME, select.KQ_NOTE_REVOKE) != (
            NOTE_DELETE, NOTE_WRITE, NOTE_EXTEND, NOTE_RENAME, NOTE_REVOKE):
        return None
    if not hasattr(os, "O_NOFOLLOW"):
        return None
    event_flag = getattr(os, "O_EVTONLY", DARWIN_O_EVTONLY)
    if type(event_flag) is not int or event_flag != DARWIN_O_EVTONLY:
        return None
    return select.KQ_FILTER_VNODE, select.KQ_EV_ADD | select.KQ_EV_CLEAR, event_flag


class DirtyHint:
    """Coalesce vnode changes into generations; scans remain authoritative."""

    def __init__(self, clock=time.monotonic, queue_factory=None, api=None, open_fd=None,
                 kevent_factory=None, fstat_fn=None, close_fd=None):
        self.clock = clock
        self._queue_factory = queue_factory or getattr(select, "kqueue", None)
        self._kevent_factory = kevent_factory or getattr(select, "kevent", None)
        self._api = _darwin_vnode_api() if api is None else api
        self._open_fd = open_fd or self._open_event_fd
        self._fstat = fstat_fn or os.fstat
        self._close_fd = close_fd or os.close
        self._queue = None
        self._paths = ()
        self._watched = {}
        self._generation = 0
        self._acknowledged = 0
        self._dirty_at = None
        self._last_scan_started = float("-inf")
        self._last_wake = float("-inf")
        self._closed = False
        self._unavailable = self._api is None
        if not self._unavailable and self._queue_factory is None:
            self._unavailable = True
        if not self._unavailable:
            try:
                self._queue = self._queue_factory()
            except (OSError, AttributeError):
                self._unavailable = True

    @property
    def available(self):
        return not self._unavailable and not self._closed

    @property
    def paths(self):
        return self._paths

    def set_paths(self, paths):
        if not isinstance(paths, (list, tuple)) or len(paths) > MAX_WATCHED_PATHS:
            self._disable()
            return False
        normalized = []
        for path in paths:
            if not isinstance(path, str) or not path or len(path) > 4096:
                self._disable()
                return False
            if not os.path.isabs(path) or "\x00" in path:
                self._disable()
                return False
            absolute = os.path.abspath(path)
            if absolute != path or absolute in normalized:
                self._disable()
                return False
            normalized.append(absolute)
        new_paths = tuple(normalized)
        if new_paths == self._paths:
            return self.available
        self._close_watched()
        self._paths = new_paths
        if not new_paths:
            self._acknowledged = self._generation
            self._dirty_at = None
            return False
        if self._unavailable:
            return False
        try:
            self._reconcile()
        except (OSError, ValueError):
            self._disable()
            return False
        self._mark_dirty()
        return True

    def poll(self, timeout=0):
        if not self.available:
            return 0
        try:
            events = self._queue.control(None, MAX_WATCHED_PATHS, max(0, timeout))
        except OSError:
            self._disable()
            return 0
        if events:
            self._mark_dirty(len(events))
        try:
            self._reconcile()
        except (OSError, ValueError):
            self._disable()
            return 0
        return len(events)

    def wait(self, timeout):
        deadline = self.clock() + max(0.0, timeout)
        starting_generation = self._generation
        while self.available:
            now = self.clock()
            self.poll(0)
            if (self._generation != starting_generation
                    and self.due_generation(now) is not None
                    and now - self._last_wake >= MIN_WAKE_INTERVAL):
                self._last_wake = now
                return
            remaining = deadline - now
            if remaining <= 0:
                return
            debounce_remaining = (0.0 if self._dirty_at is None else
                                  max(0.0, self._dirty_at + DEBOUNCE_SECONDS - now))
            wait_for = min(remaining, RECONCILE_SECONDS)
            if self._generation > self._acknowledged:
                scan_interval_remaining = max(
                    0.0, self._last_scan_started + MIN_SCAN_INTERVAL - now
                )
                wake_interval_remaining = max(
                    0.0, self._last_wake + MIN_WAKE_INTERVAL - now
                )
                until_due = max(debounce_remaining, scan_interval_remaining,
                                wake_interval_remaining)
                wait_for = min(wait_for, until_due) if until_due > 0 else min(remaining, RECONCILE_SECONDS)
            self.poll(wait_for)
        remaining = deadline - self.clock()
        if remaining > 0:
            time.sleep(remaining)

    def due_generation(self, now=None):
        if not self.available or self._generation <= self._acknowledged:
            return None
        now = self.clock() if now is None else now
        if self._dirty_at is None or now - self._dirty_at < DEBOUNCE_SECONDS:
            return None
        if now - self._last_scan_started < MIN_SCAN_INTERVAL:
            return None
        return self._generation

    def scan_started(self, now=None):
        self._last_scan_started = self.clock() if now is None else now

    def acknowledge(self, generation):
        if (isinstance(generation, int) and not isinstance(generation, bool)
                and self._acknowledged <= generation <= self._generation):
            self._acknowledged = generation
            if self._acknowledged == self._generation:
                self._dirty_at = None

    def close(self):
        if self._closed:
            return
        self._close_watched()
        if self._queue is not None:
            try:
                self._queue.close()
            except OSError:
                pass
        self._queue = None
        self._closed = True

    def _mark_dirty(self, amount=1):
        if self._generation == self._acknowledged:
            self._dirty_at = self.clock()
        self._generation += amount

    def _disable(self):
        self._close_watched()
        self._paths = ()
        self._unavailable = True

    def _close_watched(self):
        for fd in tuple(self._watched):
            try:
                self._close_fd(fd)
            except OSError:
                pass
        self._watched.clear()

    def _identity(self, path):
        if os.path.realpath(path) != path:
            raise ValueError("vnode_path_resolution_mismatch")
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError("invalid_vnode_path")
        return info.st_dev, info.st_ino, stat.S_ISDIR(info.st_mode)

    def _reconcile(self):
        desired = {}
        for path in self._paths:
            identity = self._identity(path)
            if identity is not None:
                desired[path] = identity
        for fd, (path, identity) in list(self._watched.items()):
            if desired.get(path) != identity:
                self._close_fd(fd)
                del self._watched[fd]
        current_paths = {path for path, _ in self._watched.values()}
        filter_vnode, event_flags, _ = self._api
        for path, identity in desired.items():
            if path in current_paths:
                continue
            if len(self._watched) >= MAX_WATCHED_PATHS:
                raise ValueError("watch_path_cap_exceeded")
            fd = self._open_fd(path, identity[2])
            info = self._fstat(fd)
            if (info.st_dev, info.st_ino) != identity[:2]:
                self._close_fd(fd)
                raise ValueError("watched_path_changed")
            change = self._kevent_factory(fd, filter=filter_vnode, flags=event_flags,
                                          fflags=VNODE_FFLAGS)
            try:
                self._queue.control([change], 0, 0)
            except Exception:
                self._close_fd(fd)
                raise
            self._watched[fd] = (path, identity)

    def _open_event_fd(self, path, directory):
        _, _, event_flag = self._api
        flags = event_flag | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
        fd = os.open(path, flags)
        info = self._fstat(fd)
        if directory and not stat.S_ISDIR(info.st_mode):
            self._close_fd(fd)
            raise ValueError("watched_directory_invalid")
        if not directory and not stat.S_ISREG(info.st_mode):
            self._close_fd(fd)
            raise ValueError("watched_file_invalid")
        return fd
