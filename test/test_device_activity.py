import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bridge", "device-runtime"))
import device_activity
import test_device_runtime as runtime_test

runtime = runtime_test.runtime


class ManualClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value


class ManualMonitor:
    def __init__(self, *, healthy=True, armed=False):
        self.healthy = healthy
        self.armed = armed
        self.cleanup_required = armed
        self.home_sequence = 0
        self.last_activity_at = 0.0

    def start(self):
        return None

    def snapshot(self):
        paused = not self.healthy or self.armed
        return {"healthy": self.healthy, "armed": self.armed,
                "shouldPause": paused, "cleanupRequired": self.cleanup_required,
                "homeSequence": self.home_sequence,
                "lastActivityAt": self.last_activity_at,
                "idleFor": 0.0, "reason": "manual"}

    def stop(self):
        return None

    def request_fields(self):
        return {
            "activityStatePath": "/tmp/manual.activity.json",
            "activityMonitorId": "a" * 32,
            "activityRuntimePid": 123,
            "activityResumeToken": "a" * 32 + ":123:{}:{}".format(
                self.home_sequence, 0),
        }

    def acknowledge_cleanup(self, token):
        self.cleanup_required = False
        return True


class DeviceActivityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.temp.name, "activity.json")
        self.clock = ManualClock()
        self.policy = device_activity.ActivityPolicy(
            self.state_path, clock=self.clock)
        self.assertTrue(self.policy.start_grace())
        self.policy.mark_ready()

    def tearDown(self):
        self.temp.cleanup()

    def test_startup_requires_full_idle_grace(self):
        self.assertTrue(self.policy.snapshot()["shouldPause"])
        self.clock.value += 179.999
        self.assertTrue(self.policy.snapshot()["shouldPause"])
        self.clock.value += 0.001
        self.assertFalse(self.policy.snapshot()["shouldPause"])
        with open(self.state_path, encoding="utf-8") as state_file:
            saved = json.load(state_file)
        self.assertEqual(saved["version"], device_activity.STATE_VERSION)
        self.assertEqual(saved["monitorId"], self.policy.monitor_id)
        self.assertEqual(saved["runtimePid"], os.getpid())
        self.assertTrue(saved["healthy"])
        self.assertFalse(saved["armed"])
        self.assertEqual(saved["generation"], 3)
        self.assertIsInstance(saved["publishedAt"], (int, float))

    def test_monitor_stop_invalidates_persisted_lease_immediately(self):
        monitor = device_activity.NativeActivityMonitor(
            self.state_path, clock=self.clock)
        monitor.policy.start_grace()
        monitor.policy.mark_ready()
        monitor.stop()
        with open(self.state_path, encoding="utf-8") as state_file:
            state = json.load(state_file)
        self.assertFalse(state["healthy"])
        self.assertTrue(state["armed"])

    def test_startup_grace_and_idle_stop_do_not_require_card_cleanup(self):
        self.assertFalse(self.policy.snapshot()["cleanupRequired"])
        self.clock.value += 180
        self.assertFalse(self.policy.snapshot()["shouldPause"])
        self.policy.stop()
        with open(self.state_path, encoding="utf-8") as state_file:
            stopped = json.load(state_file)
        self.assertFalse(stopped["healthy"])
        self.assertFalse(stopped["armed"])
        self.assertFalse(stopped["cleanupRequired"])

        restarted = device_activity.ActivityPolicy(self.state_path, clock=self.clock)
        self.assertTrue(restarted.start_grace())
        restarted.mark_ready()
        self.clock.value += 180
        resumed = restarted.snapshot()
        self.assertFalse(resumed["shouldPause"])
        self.assertFalse(resumed["cleanupRequired"])

    def test_saved_state_requires_complete_v4_schema_and_regular_file(self):
        valid = {
            "version": device_activity.STATE_VERSION,
            "monitorId": "a" * 32,
            "runtimePid": os.getpid(),
            "generation": 1,
            "publishedAt": 1_800_000_000.0,
            "healthy": False,
            "armed": False,
            "cleanupRequired": False,
            "lastActivityAt": 1000.0,
            "homeSequence": 0,
            "digitizerSequence": 0,
        }
        cases = []
        missing = dict(valid)
        missing.pop("cleanupRequired")
        cases.append(missing)
        wrong_cleanup = dict(valid, cleanupRequired=0)
        cases.append(wrong_cleanup)
        cases.append(dict(valid, extra=True))
        cases.append(dict(valid, version=3))
        cases.append(dict(valid, version=4.0))
        cases.append(dict(valid, version=True))
        cases.append(dict(valid, generation=True))
        cases.append(dict(valid, homeSequence=-1))
        cases.append(dict(valid, publishedAt=float("nan")))
        for state in cases:
            with self.subTest(state=state):
                with open(self.state_path, "w", encoding="utf-8") as stream:
                    json.dump(state, stream)
                self.assertEqual(
                    device_activity._load_saved_state(self.state_path), (None, True))
                unknown = device_activity.ActivityPolicy(self.state_path, clock=self.clock)
                self.assertTrue(unknown.start_grace())
                self.assertTrue(unknown.snapshot()["cleanupRequired"])

        with open(self.state_path, "w", encoding="utf-8") as stream:
            json.dump(valid, stream)
        self.assertEqual(device_activity._load_saved_state(self.state_path), (False, False))

        nonregular = os.path.join(self.temp.name, "not-a-file.activity.json")
        os.mkdir(nonregular)
        self.assertEqual(device_activity._load_saved_state(nonregular), (None, True))

        link_path = os.path.join(self.temp.name, "linked.activity.json")
        try:
            os.symlink(self.state_path, link_path)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable on this host")
        self.assertEqual(device_activity._load_saved_state(link_path), (None, True))
        dangling_path = os.path.join(self.temp.name, "dangling.activity.json")
        try:
            os.symlink(os.path.join(self.temp.name, "absent.json"), dangling_path)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable on this host")
        self.assertEqual(device_activity._load_saved_state(dangling_path), (None, True))

    def test_state_lookup_and_read_errors_require_cleanup(self):
        with patch.object(device_activity.os, "lstat", side_effect=PermissionError):
            self.assertEqual(device_activity._load_saved_state(self.state_path), (None, True))
        with patch.object(device_activity.os, "open", side_effect=PermissionError):
            self.assertEqual(device_activity._load_saved_state(self.state_path), (None, True))
        with patch.object(device_activity.os, "open", side_effect=FileNotFoundError):
            self.assertEqual(device_activity._load_saved_state(self.state_path), (None, True))

        missing_path = os.path.join(self.temp.name, "new.activity.json")
        self.assertEqual(device_activity._load_saved_state(missing_path), (None, None))
        missing = device_activity.ActivityPolicy(missing_path, clock=self.clock)
        self.assertTrue(missing.start_grace())
        self.assertFalse(missing.snapshot()["cleanupRequired"])

    def test_human_pause_survives_restart_and_cleanup_ack_is_persisted(self):
        self.policy.record_activity("home")
        self.assertTrue(self.policy.snapshot()["cleanupRequired"])
        restarted = device_activity.ActivityPolicy(self.state_path, clock=self.clock)
        self.assertTrue(restarted.start_grace())
        restarted.mark_ready()
        self.clock.value += 180
        idle = restarted.snapshot()
        self.assertFalse(idle["shouldPause"])
        self.assertTrue(idle["cleanupRequired"])
        token = "{}:{}:{}:{}".format(
            restarted.monitor_id, os.getpid(), idle["homeSequence"],
            idle["digitizerSequence"])
        self.assertTrue(restarted.acknowledge_cleanup(token))
        self.assertFalse(restarted.snapshot()["cleanupRequired"])
        with open(self.state_path, encoding="utf-8") as state_file:
            saved = json.load(state_file)
        self.assertFalse(saved["cleanupRequired"])

    def test_native_monitor_exposes_durable_state_lease_and_resume_token(self):
        monitor = device_activity.NativeActivityMonitor(self.state_path,
                                                         idle_seconds=3,
                                                         clock=self.clock)
        fields = monitor.request_fields()
        self.assertEqual(set(fields), {"activityStatePath", "activityMonitorId",
                                       "activityRuntimePid", "activityResumeToken"})
        self.assertEqual(fields["activityStatePath"], self.state_path)
        self.assertEqual(fields["activityMonitorId"], monitor.policy.monitor_id)
        self.assertEqual(fields["activityRuntimePid"], os.getpid())
        self.assertEqual(fields["activityResumeToken"],
                         f"{monitor.policy.monitor_id}:{os.getpid()}:0:0")

    def test_mirror_publishes_exact_v4_state_and_request_points_to_mirror(self):
        mirror_path = os.path.join(self.temp.name, "readable", "runtime.activity.json")
        states = []
        monitor = device_activity.NativeActivityMonitor(
            self.state_path, readable_state_path=mirror_path,
            idle_seconds=3, clock=self.clock)
        with patch.object(device_activity, "_atomic_mirror_state_write",
                          side_effect=lambda path, state: states.append((path, dict(state)))):
            self.assertTrue(monitor.policy.start_grace())
            monitor.policy.mark_ready()
            monitor.policy.record_activity("home")
            monitor.policy.stop()
        self.assertGreaterEqual(len(states), 4)
        self.assertTrue(all(path == mirror_path for path, _ in states))
        self.assertTrue(all(set(state) == device_activity.STATE_FIELDS
                            for _, state in states))
        self.assertEqual(states[-1][1]["healthy"], False)
        self.assertEqual(states[-1][1]["armed"], True)
        fields = monitor.request_fields()
        self.assertEqual(fields["activityStatePath"], mirror_path)
        self.assertEqual(fields["activityMonitorId"], monitor.policy.monitor_id)

    def test_mirror_failure_fails_closed_and_persists_unhealthy_primary_state(self):
        mirror_path = os.path.join(self.temp.name, "readable", "runtime.activity.json")
        policy = device_activity.ActivityPolicy(
            self.state_path, readable_state_path=mirror_path, clock=self.clock)
        with patch.object(device_activity, "_atomic_mirror_state_write",
                          side_effect=OSError("mirror unavailable")):
            self.assertFalse(policy.start_grace())
        state = policy.snapshot()
        self.assertFalse(state["healthy"])
        self.assertTrue(state["armed"])
        self.assertTrue(state["cleanupRequired"])
        with open(self.state_path, encoding="utf-8") as stream:
            saved = json.load(stream)
        self.assertFalse(saved["healthy"])
        self.assertTrue(saved["armed"])
        self.assertTrue(saved["cleanupRequired"])

    def test_mirror_parent_must_be_root_owned_real_directory_with_exact_mode(self):
        fake_directory = type("Stat", (), {
            "st_mode": device_activity.stat.S_IFDIR | 0o755,
            "st_uid": 0, "st_dev": 1, "st_ino": 2,
        })()
        with patch.object(device_activity.os, "name", "posix"), \
             patch.object(device_activity.os, "geteuid", return_value=0, create=True), \
             patch.object(device_activity.os, "lstat", return_value=fake_directory):
            self.assertIs(device_activity._mirror_parent_metadata(
                "/private/var/MessageCenterActivity/runtime.activity.json"),
                fake_directory)

        for metadata in (
                type("Stat", (), {"st_mode": device_activity.stat.S_IFLNK | 0o777,
                                  "st_uid": 0, "st_dev": 1, "st_ino": 2})(),
                type("Stat", (), {"st_mode": device_activity.stat.S_IFDIR | 0o755,
                                  "st_uid": 501, "st_dev": 1, "st_ino": 2})(),
                type("Stat", (), {"st_mode": device_activity.stat.S_IFDIR | 0o775,
                                  "st_uid": 0, "st_dev": 1, "st_ino": 2})()):
            with patch.object(device_activity.os, "name", "posix"), \
                 patch.object(device_activity.os, "geteuid", return_value=0, create=True), \
                 patch.object(device_activity.os, "lstat", return_value=metadata):
                with self.assertRaises(device_activity.ActivityStateError):
                    device_activity._mirror_parent_metadata(
                        "/private/var/MessageCenterActivity/runtime.activity.json")

        writable_ancestor = type("Stat", (), {
            "st_mode": device_activity.stat.S_IFDIR | 0o775,
            "st_uid": 0, "st_dev": 1, "st_ino": 3,
        })()
        with patch.object(device_activity.os, "name", "posix"), \
             patch.object(device_activity.os, "geteuid", return_value=0, create=True), \
             patch.object(device_activity.os, "lstat",
                          side_effect=[fake_directory, writable_ancestor]):
            with self.assertRaises(device_activity.ActivityStateError):
                device_activity._mirror_parent_metadata(
                    "/private/var/MessageCenterActivity/runtime.activity.json")

    def test_mirror_does_not_create_or_chmod_untrusted_directory(self):
        mirror_path = os.path.join(self.temp.name, "absent", "runtime.activity.json")
        with patch.object(device_activity.os, "name", "posix"), \
             patch.object(device_activity.os, "geteuid", return_value=0, create=True):
            with self.assertRaises(FileNotFoundError):
                device_activity._atomic_mirror_state_write(mirror_path, {})
        self.assertFalse(os.path.exists(os.path.dirname(mirror_path)))

    def test_mirror_refuses_existing_symlink_nonroot_or_wrong_mode_target(self):
        path = os.path.join(self.temp.name, "runtime.activity.json")
        parent = type("Stat", (), {"st_mode": device_activity.stat.S_IFDIR | 0o755,
                                    "st_uid": 0, "st_dev": 1, "st_ino": 2})()
        for metadata in (
                type("Stat", (), {"st_mode": device_activity.stat.S_IFLNK | 0o777,
                                  "st_uid": 0})(),
                type("Stat", (), {"st_mode": device_activity.stat.S_IFREG | 0o644,
                                  "st_uid": 501})(),
                type("Stat", (), {"st_mode": device_activity.stat.S_IFREG | 0o600,
                                  "st_uid": 0})()):
            with patch.object(device_activity, "_mirror_parent_metadata",
                              return_value=parent), \
                 patch.object(device_activity.os, "lstat", return_value=metadata), \
                 patch.object(device_activity.os, "name", "posix"), \
                 patch.object(device_activity.os, "geteuid", return_value=0, create=True):
                with self.assertRaises(device_activity.ActivityStateError):
                    device_activity._atomic_mirror_state_write(path, {})

    def test_home_and_digitizer_activity_renew_the_grace(self):
        self.clock.value += 150
        self.policy.record_activity("home")
        first = self.policy.snapshot()
        self.assertEqual(first["homeSequence"], 1)
        self.assertEqual(first["lastActivityAt"], self.clock.value)
        self.clock.value += 170
        self.assertTrue(self.policy.snapshot()["shouldPause"])
        self.policy.record_activity("digitizer")
        self.clock.value += 179.999
        self.assertTrue(self.policy.snapshot()["shouldPause"])
        self.clock.value += 0.001
        self.assertFalse(self.policy.snapshot()["shouldPause"])

    def test_clock_rollback_and_monitor_failure_fail_closed(self):
        self.clock.value -= 1
        state = self.policy.snapshot()
        self.assertFalse(state["healthy"])
        self.assertTrue(state["shouldPause"])
        self.policy.mark_ready()
        self.policy.fail("monitor_failed")
        self.clock.value += 1000
        self.assertTrue(self.policy.snapshot()["shouldPause"])

    def test_restart_rearms_pause_and_never_reuses_old_idle_interval(self):
        self.clock.value += 180
        self.assertFalse(self.policy.snapshot()["shouldPause"])
        with open(self.state_path, encoding="utf-8") as state_file:
            saved = json.load(state_file)
        self.assertFalse(saved["armed"])
        restarted = device_activity.ActivityPolicy(self.state_path, clock=self.clock)
        self.assertTrue(restarted.start_grace())
        restarted.mark_ready()
        self.assertTrue(restarted.snapshot()["shouldPause"])
        self.clock.value += 180
        self.assertFalse(restarted.snapshot()["shouldPause"])

    def test_restart_preserves_armed_pause_and_bad_state_starts_fresh_grace(self):
        self.policy.record_activity("home")
        self.policy.snapshot()
        restarted = device_activity.ActivityPolicy(self.state_path, clock=self.clock)
        self.assertTrue(restarted.start_grace())
        restarted.mark_ready()
        self.assertEqual(restarted.snapshot()["reason"], "restart_pause")
        self.clock.value += 180
        self.assertFalse(restarted.snapshot()["shouldPause"])

        with open(self.state_path, "w", encoding="utf-8") as state_file:
            state_file.write("not-json")
        unknown = device_activity.ActivityPolicy(self.state_path, clock=self.clock)
        self.assertTrue(unknown.start_grace())
        unknown.mark_ready()
        self.assertEqual(unknown.snapshot()["reason"], "restart_pause")
        self.assertTrue(unknown.snapshot()["shouldPause"])
        self.assertTrue(unknown.snapshot()["cleanupRequired"])

        with open(self.state_path, "w", encoding="utf-8") as state_file:
            state_file.write(" " * (device_activity.MAX_STATE_BYTES + 1))
        oversized = device_activity.ActivityPolicy(self.state_path, clock=self.clock)
        self.assertTrue(oversized.start_grace())
        oversized.mark_ready()
        self.assertTrue(oversized.snapshot()["shouldPause"])
        self.assertTrue(oversized.snapshot()["cleanupRequired"])

    def test_high_rate_activity_stays_in_memory_without_per_event_disk_writes(self):
        self.clock.value += 180
        self.assertFalse(self.policy.snapshot()["shouldPause"])
        with patch.object(device_activity, "_atomic_state_write") as write_state:
            for index in range(2416):
                self.clock.value += 0.01
                self.policy.record_activity("digitizer")
            self.assertEqual(write_state.call_count, 1)
        self.assertEqual(self.policy.snapshot()["homeSequence"], 0)
        self.assertTrue(self.policy.snapshot()["shouldPause"])

    def test_activity_racing_idle_checkpoint_keeps_pause_armed(self):
        self.clock.value += 180
        real_write = device_activity._atomic_state_write

        def write_then_home(path, state):
            real_write(path, state)
            with patch.object(self.policy, "_persist_current", return_value=True):
                self.policy.record_activity("home", self.clock.value + 0.001)

        with patch.object(device_activity, "_atomic_state_write", side_effect=write_then_home):
            state = self.policy.snapshot()
        self.assertTrue(state["shouldPause"])
        self.clock.value += 0.001
        self.assertTrue(self.policy.snapshot()["shouldPause"])
        with open(self.state_path, encoding="utf-8") as state_file:
            self.assertTrue(json.load(state_file)["armed"])

    def test_hid_classifier_uses_home_key_down_and_digitizer_type(self):
        class FakeIOKit:
            def __init__(self):
                self.event_type = 0
                self.fields = {}

            def IOHIDEventGetType(self, _event):
                return self.event_type

            def IOHIDEventGetIntegerValue(self, _event, field):
                return self.fields.get(field, 0)

        iokit = FakeIOKit()
        monitor = device_activity.NativeActivityMonitor(self.state_path,
                                                        clock=self.clock)
        self.assertTrue(monitor.policy.start_grace())
        monitor.policy.mark_ready()
        monitor._iokit = iokit
        iokit.event_type = device_activity.KEYBOARD_EVENT
        iokit.fields = {
            device_activity.KEYBOARD_USAGE_PAGE_FIELD: device_activity.CONSUMER_USAGE_PAGE,
            device_activity.KEYBOARD_USAGE_FIELD: device_activity.HOME_USAGE,
            device_activity.KEYBOARD_DOWN_FIELD: 0,
        }
        monitor._consume_event(1)
        self.assertEqual(monitor.policy.snapshot()["homeSequence"], 0)
        iokit.fields[device_activity.KEYBOARD_DOWN_FIELD] = 1
        monitor._consume_event(1)
        self.assertEqual(monitor.policy.snapshot()["homeSequence"], 1)
        iokit.event_type = device_activity.DIGITIZER_EVENT
        self.clock.value += 1
        monitor._consume_event(2)
        self.assertEqual(monitor.policy.snapshot()["lastActivityAt"], self.clock.value)
        self.assertEqual(monitor.policy.snapshot()["digitizerSequence"], 1)

    def test_binding_requires_verified_unschedule_export_name(self):
        class Function:
            def __call__(self, *_args):
                return 1

        class FakeIOKit:
            def __init__(self, *, include_verified=True):
                for name in (
                    "IOHIDEventSystemClientCreateWithType",
                    "IOHIDEventSystemClientRegisterEventCallback",
                    "IOHIDEventSystemClientUnregisterEventCallback",
                    "IOHIDEventSystemClientScheduleWithRunLoop",
                    "IOHIDEventGetType",
                    "IOHIDEventGetIntegerValue",
                ):
                    setattr(self, name, Function())
                if include_verified:
                    self.IOHIDEventSystemClientUnscheduleWithRunLoop = Function()

        class FakeCF:
            def __init__(self):
                self.CFRunLoopGetCurrent = Function()
                self.CFRunLoopRunInMode = Function()
                self.CFRelease = Function()

        monitor = device_activity.NativeActivityMonitor(self.state_path,
                                                        clock=self.clock)
        monitor._iokit = FakeIOKit()
        monitor._cf = FakeCF()
        with patch.object(device_activity.ctypes.c_void_p, "in_dll",
                          return_value=type("Mode", (), {"value": 1})()):
            monitor._bind()

        monitor._iokit = FakeIOKit(include_verified=False)
        with patch.object(device_activity.ctypes.c_void_p, "in_dll",
                          return_value=type("Mode", (), {"value": 1})()):
            with self.assertRaises(AttributeError):
                monitor._bind()

class DeviceActivityRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "runtime.sqlite3")
        self.config = {
            "serviceUrl": "https://worker.example",
            "database": self.db_path,
            "adapter": "unused-private-adapter",
            "connectors": [{"id": "connector-a", "token": "x" * 40,
                            "kind": "qq", "accountLabel": "test", "displayName": "device",
                            "profile": "primary"}],
            "outboxMaxBytes": 100000,
            "pageLimit": 20,
        }
        self.db = runtime.open_database(self.db_path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def make_relay(self, monitor, adapter_call=None, http_call=None, config=None):
        return runtime.Relay(config or self.config, self.db,
                             adapter_call=adapter_call or (lambda _: {}),
                             http_call=http_call or (lambda *_args: {"ok": True}),
                             activity_monitor=monitor)

    def test_runtime_adapter_requests_carry_monitor_identity_and_state_path(self):
        monitor = ManualMonitor()
        monitor.request_fields = lambda: {
            "activityStatePath": self.db_path + ".activity.json",
            "activityMonitorId": "a" * 32,
            "activityRuntimePid": 123,
            "activityResumeToken": "a" * 32 + ":123:0:0",
        }
        calls = []
        relay = self.make_relay(monitor, lambda request: calls.append(request) or {})
        relay.call_adapter({"op": "scan", "driver": "qq"})
        self.assertEqual(calls, [{"op": "scan", "driver": "qq",
                                  "activityStatePath": self.db_path + ".activity.json",
                                  "activityMonitorId": "a" * 32,
                                  "activityRuntimePid": 123,
                                  "activityResumeToken": "a" * 32 + ":123:0:0"}])
        relay.close()

    def test_resume_cleanup_signal_is_sent_once_after_activity_ends(self):
        monitor = ManualMonitor(armed=True)
        monitor.request_fields = lambda: {
            "activityStatePath": self.db_path + ".activity.json",
            "activityMonitorId": "a" * 32,
            "activityRuntimePid": 123,
            "activityResumeToken": "a" * 32 + ":123:0:0",
        }
        calls = []
        replies = [RuntimeError("adapter unavailable"),
                   {"activityResumeCleanupComplete": True,
                    "activityResumeCleanupToken": "a" * 32 + ":123:0:0"}, {}]

        def adapter(request):
            calls.append(request)
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        relay = self.make_relay(monitor, adapter)
        self.assertTrue(relay.activity_state()["shouldPause"])
        monitor.armed = False
        self.assertFalse(relay.activity_state()["shouldPause"])
        with self.assertRaisesRegex(RuntimeError, "adapter unavailable"):
            relay.call_adapter({"op": "ensure-active", "driver": "qq"})
        relay.call_adapter({"op": "ensure-active", "driver": "qq"})
        relay.call_adapter({"op": "ensure-active", "driver": "qq"})
        self.assertTrue(calls[0]["activityResumeCleanup"])
        self.assertEqual(calls[0]["activityResumeToken"], "a" * 32 + ":123:0:0")
        self.assertTrue(calls[1]["activityResumeCleanup"])
        self.assertNotIn("activityResumeCleanup", calls[2])
        relay.close()

    def test_ensure_active_accepts_completion_ack_and_clears_pending_cleanup(self):
        monitor = ManualMonitor(armed=True)
        token = "a" * 32 + ":123:0:0"
        monitor.request_fields = lambda: {
            "activityStatePath": self.db_path + ".activity.json",
            "activityMonitorId": "a" * 32,
            "activityRuntimePid": 123,
            "activityResumeToken": token,
        }
        requests = []

        def adapter(request):
            requests.append(request)
            return {"ok": True, "ready": False, "attempted": True,
                    "reason": "qq_resume_cleanup_submitted",
                    "activityResumeCleanupComplete": True,
                    "activityResumeCleanupToken": token}

        config = dict(self.config, autoWake=True)
        relay = self.make_relay(monitor, adapter, config=config)
        relay.activity_state()
        monitor.armed = False
        relay.activity_state()
        self.assertFalse(relay.ensure_active())
        self.assertTrue(requests[0]["activityResumeCleanup"])
        self.assertFalse(relay.activity_resume_pending)
        self.assertFalse(relay.wake_ready)
        relay.close()

    def test_startup_grace_resume_does_not_request_cleanup(self):
        monitor = ManualMonitor(armed=True)
        monitor.cleanup_required = False
        calls = []
        relay = self.make_relay(
            monitor, lambda request: calls.append(request) or
            {"ok": True, "ready": True, "attempted": False, "reason": "ready"},
            config=dict(self.config, autoWake=True))
        self.assertTrue(relay.activity_state()["shouldPause"])
        monitor.armed = False
        relay.activity_state()
        relay.ensure_active()
        self.assertEqual(len(calls), 1)
        self.assertNotIn("activityResumeCleanup", calls[0])
        relay.close()

    def test_unrequested_cleanup_ack_is_not_stripped(self):
        monitor = ManualMonitor()
        monitor.request_fields = lambda: {
            "activityStatePath": self.db_path + ".activity.json",
            "activityMonitorId": "a" * 32,
            "activityRuntimePid": 123,
            "activityResumeToken": "a" * 32 + ":123:0:0",
        }
        relay = self.make_relay(
            monitor,
            lambda _request: {"ok": True, "ready": False, "attempted": False,
                              "reason": "activity_state_unknown",
                              "activityResumeCleanupComplete": True,
                              "activityResumeCleanupToken": "a" * 32 + ":123:0:0"},
            config=dict(self.config, autoWake=True))
        self.assertFalse(relay.ensure_active())
        self.assertFalse(relay.wake_ready)
        relay.close()

    def event(self, ident):
        return {"externalId": ident, "conversationExternalId": "conversation-aaaaaaaa",
                "conversationTitle": "Test", "senderName": "Sender",
                "occurredAt": "2026-10-07T12:00:00.000Z", "body": ident}

    def event_ack(self, received):
        return {"ok": True, "received": received, "inserted": received,
                "upgraded": 0, "promoted": 0, "suppressed": 0}

    def test_human_use_pauses_ui_paths_and_keeps_outbox_flush_offline(self):
        monitor = ManualMonitor(armed=True)
        adapter_calls = []
        requests = []

        def http(method, path, payload=None):
            requests.append((method, path, payload))
            if path.endswith("/events"):
                return self.event_ack(1)
            if path.endswith("/heartbeat"):
                return {"ok": True}
            if "/commands?" in path:
                return {"commands": []}
            return {"ok": True}

        relay = self.make_relay(monitor, lambda request: adapter_calls.append(request) or {}, http)
        event = self.event("already-collected")
        body = runtime.compact(event)
        self.db.execute(
            "INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,?)",
            ("connector-a", "primary", event["externalId"], body, len(body.encode("utf-8"))),
        )
        self.db.commit()
        with patch.object(relay, "scan_profile", side_effect=AssertionError("scan during human use")):
            relay.pass_once()
        self.assertEqual(adapter_calls, [])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)
        self.assertFalse(any("/commands?" in path for _, path, _ in requests))
        heartbeat_states = [payload["state"] for _, path, payload in requests
                            if path.endswith("/heartbeat")]
        self.assertTrue(heartbeat_states)
        self.assertEqual(set(heartbeat_states), {"offline"})
        relay.close()

    def test_resume_requires_a_fresh_read_before_online_heartbeat(self):
        monitor = ManualMonitor(armed=True)
        requests = []

        def http(method, path, payload=None):
            requests.append((method, path, payload))
            if "/commands?" in path:
                return {"commands": []}
            return {"ok": True}

        relay = self.make_relay(monitor, http_call=http)
        relay.pass_once()
        monitor.armed = False
        with patch.object(relay, "scan_profile", return_value=True) as scan:
            relay.pass_once()
        self.assertEqual(scan.call_count, 1)
        heartbeat_states = [payload["state"] for _, path, payload in requests
                            if path.endswith("/heartbeat")]
        self.assertEqual(heartbeat_states[-1], "online")
        relay.close()

    def test_unhealthy_monitor_blocks_automatic_wake_and_commands(self):
        monitor = ManualMonitor(healthy=False, armed=False)
        adapter_calls = []
        http_calls = []
        config = dict(self.config, autoWake=True)
        relay = self.make_relay(
            monitor,
            lambda request: adapter_calls.append(request) or {},
            lambda *args: http_calls.append(args) or {"commands": []},
            config=config,
        )
        relay.pass_once()
        self.assertEqual(adapter_calls, [])
        self.assertFalse(any("/commands?" in args[1] for args in http_calls))
        command = {"idempotencyKey": "unused-key", "payload": {}}
        self.assertFalse(relay.process_command(command, "primary"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM command_ledger").fetchone()[0], 0)
        relay.close()

    def test_activity_after_lease_retries_only_before_dispatch(self):
        monitor = ManualMonitor()
        adapter_calls = []
        requests = []

        def http(method, path, payload=None):
            requests.append((method, path, payload))
            if path.endswith("/lease"):
                monitor.armed = True
            return {"ok": True}

        relay = self.make_relay(monitor,
                                lambda request: adapter_calls.append(request) or {}, http)
        relay.process_command({"id": "command-a", "idempotencyKey": "key-a",
                              "leaseToken": "lease-a", "payload": {
                                  "externalConversationId": "conversation-aaaaaaaa",
                                  "body": "hello", "attachments": []}}, "primary")
        self.assertEqual(adapter_calls, [])
        ledger = self.db.execute(
            "SELECT state,retryable FROM command_ledger WHERE idempotency_key='key-a'").fetchone()
        self.assertEqual(ledger, ("retry", 1))
        completion = next(payload for method, path, payload in requests
                          if method == "POST" and path.endswith("/complete"))
        self.assertTrue(completion["retry"])
        self.assertFalse(completion["dispatched"])
        relay.close()


if __name__ == "__main__":
    unittest.main()
