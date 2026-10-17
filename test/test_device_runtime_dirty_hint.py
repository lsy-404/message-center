import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge" / "device-runtime"))
import dirty_hint


class FakeClock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeQueue:
    def __init__(self):
        self.events = []
        self.changelists = []
        self.closed = False

    def control(self, changes, max_events, timeout):
        if changes is not None:
            self.changelists.extend(changes)
            return []
        events, self.events = self.events[:max_events], self.events[max_events:]
        return events

    def close(self):
        self.closed = True


class DirtyHintTests(unittest.TestCase):
    def _watcher(self, clock, queue):
        descriptors = {}
        next_fd = [100]

        def open_fd(path, directory):
            next_fd[0] += 1
            descriptors[next_fd[0]] = os.stat(path)
            return next_fd[0]

        def close_fd(fd):
            descriptors.pop(fd, None)

        watcher = dirty_hint.DirtyHint(
            clock=clock,
            queue_factory=lambda: queue,
            api=(-4, 0x21, dirty_hint.DARWIN_O_EVTONLY),
            open_fd=open_fd,
            kevent_factory=lambda fd, **kwargs: SimpleNamespace(ident=fd, **kwargs),
            fstat_fn=lambda fd: descriptors[fd],
            close_fd=close_fd,
        )
        watcher._test_descriptors = descriptors
        return watcher

    def test_generation_requires_debounce_and_minimum_interval_and_ack_is_exact(self):
        clock = FakeClock()
        queue = FakeQueue()
        watcher = self._watcher(clock, queue)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.db"
            path.write_bytes(b"fixture")
            self.assertTrue(watcher.set_paths([str(path)]))
            self.assertIsNone(watcher.due_generation())
            clock.advance(1.1)
            first_generation = watcher.due_generation()
            self.assertEqual(first_generation, 1)
            watcher.scan_started()

            queue.events = [SimpleNamespace(ident=next(iter(watcher._watched)), fflags=dirty_hint.NOTE_WRITE)]
            watcher.poll()
            self.assertEqual(watcher._generation, 2)
            watcher.acknowledge(first_generation)
            self.assertIsNone(watcher.due_generation())
            clock.advance(4.0)
            self.assertIsNone(watcher.due_generation())
            clock.advance(1.0)
            self.assertEqual(watcher.due_generation(), 2)
            watcher.acknowledge(2)
            self.assertIsNone(watcher.due_generation())
        watcher.close()
        self.assertTrue(queue.closed)

    def test_failed_scan_or_invalid_ack_keeps_generation_pending(self):
        clock = FakeClock()
        watcher = self._watcher(clock, FakeQueue())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.db"
            path.write_bytes(b"fixture")
            watcher.set_paths([str(path)])
            clock.advance(1.1)
            generation = watcher.due_generation()
            watcher.acknowledge(generation + 1)
            self.assertEqual(watcher.due_generation(), generation)
            watcher.acknowledge(True)
            self.assertEqual(watcher.due_generation(), generation)
        watcher.close()

    def test_wait_wakes_when_polled_generation_is_already_due(self):
        clock = FakeClock()
        queue = FakeQueue()
        watcher = self._watcher(clock, queue)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.db"
            path.write_bytes(b"fixture")
            watcher.set_paths([str(path)])
            fd = next(iter(watcher._watched))
            queue.events = [SimpleNamespace(ident=fd, fflags=dirty_hint.NOTE_WRITE)]
            watcher.poll()
            clock.advance(dirty_hint.DEBOUNCE_SECONDS + 0.1)
            watcher.wait(0)
            self.assertEqual(watcher._last_wake, clock())
            self.assertEqual(watcher.due_generation(), watcher._generation)
        watcher.close()

    def test_transient_queue_failure_recovers_at_bounded_retry(self):
        clock = FakeClock()
        first, recovered = FakeQueue(), FakeQueue()
        original_control = first.control

        def fail_once(changes, max_events, timeout):
            if changes is not None:
                return original_control(changes, max_events, timeout)
            first.control = original_control
            raise OSError("temporary kqueue failure")

        first.control = fail_once
        queues = iter((first, recovered))
        descriptors = {}
        next_fd = [100]

        def open_fd(path, directory):
            next_fd[0] += 1
            descriptors[next_fd[0]] = os.stat(path)
            return next_fd[0]

        watcher = dirty_hint.DirtyHint(
            clock=clock, queue_factory=lambda: next(queues),
            api=(-4, 0x21, dirty_hint.DARWIN_O_EVTONLY), open_fd=open_fd,
            kevent_factory=lambda fd, **kwargs: SimpleNamespace(ident=fd, **kwargs),
            fstat_fn=lambda fd: descriptors[fd], close_fd=descriptors.pop,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.db"
            path.write_bytes(b"fixture")
            self.assertTrue(watcher.set_paths([str(path)]))
            watcher.poll()
            self.assertTrue(watcher.available)
            self.assertEqual(watcher._paths, (str(path),))
            self.assertFalse(watcher._watched)
            self.assertEqual(watcher.poll(), 0)
            clock.advance(dirty_hint.RETRY_SECONDS)
            self.assertEqual(watcher.poll(), 0)
            self.assertIs(watcher._queue, recovered)
            self.assertEqual(len(watcher._watched), 1)
        watcher.close()

    def test_later_events_coalesce_without_resetting_debounce_deadline(self):
        clock = FakeClock()
        queue = FakeQueue()
        watcher = self._watcher(clock, queue)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.db"
            path.write_bytes(b"fixture")
            watcher.set_paths([str(path)])
            clock.advance(1.1)
            first_generation = watcher.due_generation()
            watcher.scan_started()
            watcher.acknowledge(first_generation)
            clock.advance(0.2)
            fd = next(iter(watcher._watched))
            queue.events = [SimpleNamespace(ident=fd, fflags=dirty_hint.NOTE_WRITE)]
            watcher.poll()
            clock.advance(0.8)
            queue.events = [SimpleNamespace(ident=fd, fflags=dirty_hint.NOTE_WRITE)]
            watcher.poll()
            self.assertIsNone(watcher.due_generation())
            clock.advance(4.0)
            self.assertEqual(watcher.due_generation(), 3)
        watcher.close()

    def test_path_rotation_reconciles_descriptors_and_empty_paths_clear_pending(self):
        clock = FakeClock()
        queue = FakeQueue()
        watcher = self._watcher(clock, queue)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.db"
            replacement = Path(temporary) / "replacement.db"
            path.write_bytes(b"old")
            watcher.set_paths([str(path)])
            old_fd = next(iter(watcher._watched))
            old_identity = watcher._watched[old_fd][1][:2]
            path.rename(replacement)
            path.write_bytes(b"new")
            watcher.poll()
            self.assertEqual(len(watcher._watched), 1)
            self.assertEqual(len(watcher._test_descriptors), 1)
            self.assertNotEqual(watcher._watched[next(iter(watcher._watched))][1][:2], old_identity)
            self.assertFalse(watcher.set_paths([]))
            self.assertIsNone(watcher.due_generation())
        watcher.close()

    def test_rejects_nonabsolute_duplicate_and_over_cap_paths(self):
        watcher = self._watcher(FakeClock(), FakeQueue())
        self.assertFalse(watcher.set_paths(["relative/path"]))
        self.assertFalse(watcher.available)
        watcher.close()

    def test_unsupported_platform_keeps_polling_fallback(self):
        with mock.patch.object(dirty_hint.sys, "platform", "win32"), \
             mock.patch.object(dirty_hint.platform, "system", return_value="Windows"):
            watcher = dirty_hint.DirtyHint()
        self.assertFalse(watcher.available)
        watcher.wait(0)
        watcher.close()


if __name__ == "__main__":
    unittest.main()
