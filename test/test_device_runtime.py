import base64
import importlib.util
import http.server
import io
import json
import os
import signal
import sqlite3
import stat
import tempfile
import sys
import threading
import time
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bridge", "device-runtime"))
import conversation_profiles
SOURCE = os.path.join(ROOT, "bridge", "device-runtime", "device_runtime.py")
SPEC = importlib.util.spec_from_file_location("device_runtime", SOURCE)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


def qq_receipt_result():
    receipt = {"sourceId": "9007199254740993", "messageAlias": "message-aeb18cd1",
               "messageType": 1, "sendStatus": 2, "confirmation": "verified-status"}
    return {"ok": True, "dispatched": True,
            "receipt": json.dumps(receipt, separators=(",", ":")),
            "externalId": "primary:qq-message:9007199254740993"}


class DeviceRuntimeTests(unittest.TestCase):
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
        self.inactive_monitors = []

        # Keep ordinary relay fixtures platform-neutral; Darwin bootstrap has a dedicated test below.
        self.platform_patch = patch.object(runtime.device_activity.platform, "system", return_value="Windows")
        self.platform_patch.start()

        def inactive_monitor(_path, **_kwargs):
            monitor = runtime.device_activity.InactiveHostMonitor()
            self.inactive_monitors.append(monitor)
            return monitor

        self.activity_factory_patch = patch.object(
            runtime.device_activity, "create_monitor", side_effect=inactive_monitor)
        self.activity_factory_patch.start()

    def tearDown(self):
        self.activity_factory_patch.stop()
        self.platform_patch.stop()
        for monitor in self.inactive_monitors:
            monitor.stop()
        self.db.close()
        self.temp.cleanup()

    def test_darwin_activity_uses_fixed_rootless_shared_mirror(self):
        path = runtime.device_activity.SHARED_MIRROR_ALIAS
        monitor = runtime.device_activity.InactiveHostMonitor()
        with patch.object(runtime.device_activity.platform, "system", return_value="Darwin"), \
             patch.object(runtime, "run_adapter") as adapter, \
             patch.object(runtime.device_activity, "create_monitor", return_value=monitor) as factory:
            relay = runtime.Relay(self.config, db=self.db)
            factory.assert_called_once_with(self.db_path + ".activity.json", readable_state_path=path)
            adapter.assert_not_called()
            relay.close()

    def test_darwin_activity_rejects_untrusted_shared_mirror_root(self):
        with patch.object(runtime.device_activity.platform, "system", return_value="Darwin"), \
             patch.object(runtime.device_activity.os.path, "realpath", return_value="/tmp/outside"):
            monitor = runtime.device_activity.InactiveHostMonitor()
            with patch.object(runtime.device_activity, "create_monitor", return_value=monitor):
                relay = runtime.Relay(self.config, db=self.db)
                with self.assertRaisesRegex(runtime.device_activity.ActivityStateError, "mirror_root_invalid"):
                    runtime.device_activity._atomic_mirror_state_write(
                        runtime.device_activity.SHARED_MIRROR_ALIAS, {})
                relay.close()

    def test_darwin_activity_rejects_shared_alias_escape(self):
        with patch.object(runtime.device_activity.os.path, "realpath", side_effect=lambda value:
                          "/private/preboot/JBROOT" if value == "/var/jb" else "/tmp/outside"):
            with self.assertRaisesRegex(runtime.device_activity.ActivityStateError, "mirror_path_invalid"):
                runtime.device_activity._atomic_mirror_state_write(
                    runtime.device_activity.SHARED_MIRROR_ALIAS, {})

    def event(self, ident):
        return {"externalId": ident, "conversationExternalId": "conversation-aaaaaaaa",
                "conversationTitle": "Test", "senderName": "Sender",
                "occurredAt": "2026-10-07T12:00:00.000Z", "body": ident}

    def save_cursor(self, connector_id="connector-a", profile="primary", cursor=None):
        if cursor is None:
            cursor = {"version": 1, "conversations": {},
                      "qqFriendDirectory": {
                          "version": "qfd1", "ownerUin": "1234", "entries": [],
                          "lastAttemptUin": None, "lastAttemptAt": 0, "nextMainItem": 0,
                      }}
        self.db.execute(
            "INSERT INTO cursors(connector_id,profile,value) VALUES(?,?,?) "
            "ON CONFLICT(connector_id,profile) DO UPDATE SET value=excluded.value",
            (connector_id, profile, runtime.compact(cursor)),
        )
        self.db.commit()
        return cursor

    def event_ack(self, received, inserted=None, upgraded=0, promoted=0, suppressed=0):
        return {"ok": True, "received": received,
                "inserted": received if inserted is None else inserted,
                "upgraded": upgraded, "promoted": promoted, "suppressed": suppressed}

    def test_qq_receipt_identity_requires_exact_native_id_alias_and_profile(self):
        valid = qq_receipt_result()
        self.assertTrue(runtime.verified_qq_external_id(
            "primary", valid["externalId"], valid["receipt"]))
        self.assertFalse(runtime.verified_qq_external_id(
            "other-profile", valid["externalId"], valid["receipt"]))
        self.assertFalse(runtime.verified_qq_external_id(
            "primary", "primary:qq-message:9007199254740992", valid["receipt"]))
        collision_receipt = json.loads(valid["receipt"])
        collision_receipt["sourceId"] = "2328622970"
        collision_receipt["messageAlias"] = "message-e37f9132"
        self.assertTrue(runtime.verified_qq_external_id(
            "primary", "primary:qq-message:2328622970", json.dumps(collision_receipt)))
        self.assertFalse(runtime.verified_qq_external_id(
            "primary", "primary:qq-message:2948735191", json.dumps(collision_receipt)))
        bad_receipt = json.loads(valid["receipt"])
        bad_receipt["sourceId"] = "9007199254740992"
        self.assertFalse(runtime.verified_qq_external_id(
            "primary", valid["externalId"], json.dumps(bad_receipt)))
        bad_receipt = json.loads(valid["receipt"])
        bad_receipt["sendStatus"] = 3
        self.assertFalse(runtime.verified_qq_external_id(
            "primary", valid["externalId"], json.dumps(bad_receipt)))

    def test_qq_command_conversation_id_uses_raw_worker_external_alias(self):
        self.assertEqual(
            runtime.qq_command_conversation_alias("conversation-aaaaaaaa"),
            "conversation-aaaaaaaa",
        )
        self.assertIsNone(runtime.qq_command_conversation_alias("primary:conversation-aaaaaaaa"))
        self.assertIsNone(runtime.qq_command_conversation_alias("conversation-aaaaaaaa:primary"))
        self.assertIsNone(runtime.qq_command_conversation_alias("conversation-AAAAAAAA"))

    def backup_ack(self, received, inserted=None, normalized_inserted=None):
        return {"ok": True, "received": received,
                "inserted": received if inserted is None else inserted,
                "normalizedInserted": received if normalized_inserted is None else normalized_inserted,
                "retentionDays": 30}

    def test_profile_sync_failure_preserves_cursor_and_outbox(self):
        result = {"ok": True, "sourceReadOk": True, "health": "online", "cursor": {"next": "2"},
                  "messages": [self.event("new-1")],
                  "conversationProfiles": [{"conversationExternalId": "conversation-aaaaaaaa", "displayName": "中文 😀"}]}
        relay = runtime.Relay(self.config, self.db, lambda _: result)
        with patch.object(runtime, "sync_profiles", side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError):
                relay.scan_profile("primary")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM cursors").fetchone()[0], 0)
        with patch.object(runtime, "sync_profiles", return_value=1) as synchronized:
            relay.scan_profile("primary")
            self.assertEqual(synchronized.call_args.args[1], result["conversationProfiles"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM cursors").fetchone()[0], 1)

    def test_receive_hint_paths_are_allowlisted_and_published_only_after_durable_scan(self):
        class Watcher:
            def __init__(self):
                self.paths = None
                self.closed = False

            def set_paths(self, paths):
                self.paths = paths

            def close(self):
                self.closed = True

        paths = ["/private/preboot/JBROOT/var/mobile/Library/MessageCenterReceiveHints/signals/changed.json",
                 "/private/preboot/JBROOT/var/mobile/Library/MessageCenterReceiveHints/signals"]
        result = {"ok": True, "sourceReadOk": True, "health": "online",
                  "cursor": {"next": "2"}, "messages": [self.event("new-1")],
                  "receiveHintPaths": paths}
        watcher = Watcher()
        relay = runtime.Relay(self.config, self.db, lambda _: result,
                              dirty_watcher=watcher)
        with patch.object(runtime, "resolve_qq_receive_hint_paths", return_value=tuple(paths)):
            relay.scan_profile("primary")
        self.assertEqual(watcher.paths, tuple(paths))
        self.assertNotIn("receiveHintPaths", result)
        self.assertNotIn("receiveHintPaths", json_cursor(self.db))
        stored_body = self.db.execute("SELECT body FROM outbox").fetchone()[0]
        self.assertNotIn("/private/container", stored_body)
        relay.close()
        self.assertTrue(watcher.closed)

    def test_receive_hint_paths_reject_arbitrary_local_paths_and_clear_watcher(self):
        class Watcher:
            def __init__(self):
                self.paths = ["/private/preboot/JBROOT/var/mobile/Library/MessageCenterReceiveHints/signals"]

            def set_paths(self, paths):
                self.paths = paths

            def close(self):
                pass

        result = {"ok": True, "sourceReadOk": True, "health": "online",
                  "cursor": {"next": "2"}, "messages": [self.event("new-1")],
                  "receiveHintPaths": ["/private/container/nt_msg.db", "/private/container"]}
        watcher = Watcher()
        relay = runtime.Relay(self.config, self.db, lambda _: result,
                              dirty_watcher=watcher)
        relay.scan_profile("primary")
        self.assertEqual(watcher.paths, [])
        self.assertNotIn("/private/container", json.dumps(json_cursor(self.db)))

    def test_receive_hint_paths_are_not_activated_for_failed_scan(self):
        class Watcher:
            def __init__(self):
                self.paths = None

            def set_paths(self, paths):
                self.paths = paths

            def close(self):
                pass

        watcher = Watcher()
        result = {"ok": True, "sourceReadOk": False, "health": "offline",
                  "cursor": {"next": "2"}, "messages": [],
                  "receiveHintPaths": ["/private/container/nt_msg.db"]}
        relay = runtime.Relay(self.config, self.db, lambda _: result,
                              dirty_watcher=watcher)
        with self.assertRaises(runtime.SourceReadError):
            relay.scan_profile("primary")
        self.assertIsNone(watcher.paths)
        self.assertNotIn("receiveHintPaths", result)

    def test_qq_receive_hint_allowlist_validates_canonical_metadata(self):
        root = "/private/preboot/JBROOT/var/mobile/Library/MessageCenterReceiveHints"
        paths = (root + "/signals/changed.json", root + "/signals")

        def fake_realpath(path):
            return "/private/preboot/JBROOT" if path == "/var/jb" else path

        def fake_lstat(path):
            if path == root:
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
            if path == paths[1]:
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=501)
            if path == paths[0]:
                return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=501)
            raise FileNotFoundError(path)

        with patch.object(runtime.device_activity.platform, "system", return_value="Darwin"), \
                patch.object(runtime.os.path, "realpath", side_effect=fake_realpath), \
                patch.object(runtime.os, "lstat", side_effect=fake_lstat), \
                patch.dict(sys.modules, {"pwd": SimpleNamespace(
                    getpwnam=lambda _name: SimpleNamespace(pw_uid=501))}):
            self.assertEqual(runtime.resolve_qq_receive_hint_paths(list(paths)), paths)
            self.assertIsNone(runtime.resolve_qq_receive_hint_paths([root + "/other", paths[1]]))

    def test_qq_receive_hint_allowlist_rejects_symlinked_signal_directory(self):
        root = "/private/preboot/JBROOT/var/mobile/Library/MessageCenterReceiveHints"
        paths = (root + "/signals/changed.json", root + "/signals")

        def fake_realpath(path):
            if path == "/var/jb":
                return "/private/preboot/JBROOT"
            return root if path == paths[1] else path

        with patch.object(runtime.device_activity.platform, "system", return_value="Darwin"), \
                patch.object(runtime.os.path, "realpath", side_effect=fake_realpath), \
                patch.dict(sys.modules, {"pwd": SimpleNamespace(
                    getpwnam=lambda _name: SimpleNamespace(pw_uid=501))}):
            self.assertIsNone(runtime.resolve_qq_receive_hint_paths(paths))

    def test_dirty_scan_ack_requires_durable_scan_and_never_bypasses_existing_gates(self):
        class Watcher:
            def __init__(self):
                self.generation = 9
                self.acknowledged = []
                self.started = 0

            def poll(self, _timeout):
                pass

            def due_generation(self):
                return self.generation

            def scan_started(self):
                self.started += 1

            def acknowledge(self, generation):
                self.acknowledged.append(generation)

            def set_paths(self, _paths):
                pass

            def close(self):
                pass

        watcher = Watcher()
        result = {"ok": True, "sourceReadOk": True, "health": "online",
                  "cursor": {"next": "2"}, "messages": []}
        adapter_calls = []
        order = []
        relay = runtime.Relay(self.config, self.db,
                              lambda request: (order.append("scan"), adapter_calls.append(request), result)[2],
                              lambda *_args: {"commands": []}, dirty_watcher=watcher)
        flush_results = iter(("connector-a", None))
        relay.flush_one = lambda: (order.append("outbox"), next(flush_results))[1]
        relay.ensure_active = lambda: True
        relay.activity_paused = lambda: False
        relay.send_heartbeat = lambda *_args: None
        relay.pass_once()
        self.assertEqual(watcher.acknowledged, [9])
        self.assertEqual(watcher.started, 1)
        self.assertEqual(len(adapter_calls), 1)
        self.assertEqual(order, ["outbox", "outbox", "scan"])

        blocked_watcher = Watcher()
        blocked_calls = []
        blocked = runtime.Relay(self.config, self.db,
                                lambda request: blocked_calls.append(request) or result,
                                lambda *_args: {"commands": []}, dirty_watcher=blocked_watcher)
        blocked.flush_one = lambda: None
        blocked.ensure_active = lambda: True
        blocked.activity_paused = lambda: False
        blocked.eligible = lambda _connector_id: False
        blocked.send_heartbeat = lambda *_args: None
        blocked.pass_once()
        self.assertEqual(blocked_calls, [])
        self.assertEqual(blocked_watcher.acknowledged, [])

        capacity_watcher = Watcher()
        capacity = runtime.Relay(self.config, self.db, lambda _request: result,
                                 lambda *_args: {"commands": []},
                                 dirty_watcher=capacity_watcher)
        capacity.flush_one = lambda: None
        capacity.ensure_active = lambda: True
        capacity.activity_paused = lambda: False
        capacity.send_heartbeat = lambda *_args: None
        capacity.scan_profile = lambda _profile: None
        capacity.pass_once()
        self.assertEqual(capacity_watcher.acknowledged, [])

        wake_config = dict(self.config, autoWake=True)
        sleeping_watcher = Watcher()
        sleeping_calls = []
        sleeping = runtime.Relay(wake_config, self.db,
                                 lambda request: sleeping_calls.append(request) or result,
                                 lambda *_args: {"commands": []},
                                 dirty_watcher=sleeping_watcher)
        sleeping.flush_one = lambda: None
        sleeping.ensure_active = lambda: False
        sleeping.activity_paused = lambda: False
        sleeping.send_heartbeat = lambda *_args: None
        sleeping.pass_once()
        self.assertEqual(sleeping_calls, [])
        self.assertEqual(sleeping_watcher.acknowledged, [])

        failed_watcher = Watcher()
        failed = runtime.Relay(self.config, self.db,
                               lambda _request: (_ for _ in ()).throw(RuntimeError("read failed")),
                               lambda *_args: {"commands": []}, dirty_watcher=failed_watcher)
        failed.flush_one = lambda: None
        failed.ensure_active = lambda: True
        failed.activity_paused = lambda: False
        failed.send_heartbeat = lambda *_args: None
        failed.pass_once()
        self.assertEqual(failed_watcher.acknowledged, [])

    def test_failed_native_read_does_not_commit_cursor_messages_or_profiles(self):
        self.db.execute(
            "INSERT INTO cursors(connector_id,profile,value) VALUES(?,?,?)",
            ("connector-a", "primary", runtime.compact({"next": "old"})),
        )
        self.db.commit()
        result = {"ok": True, "sourceReadOk": False, "health": "offline",
                  "cursor": {"next": "new"}, "messages": [self.event("must-not-spool")],
                  "conversationProfiles": [{"conversationExternalId": "private", "displayName": "ignored"}]}
        relay = runtime.Relay(self.config, self.db, lambda _request: result)
        with patch.object(runtime, "sync_profiles") as sync_profiles:
            with self.assertRaises(runtime.SourceReadError):
                relay.scan_profile("primary")
        sync_profiles.assert_not_called()
        self.assertEqual(json_cursor(self.db), runtime.compact({"next": "old"}))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)

    def test_source_read_ok_commits_degraded_thumbnail_backlog_without_failure_recovery(self):
        result = {"ok": True, "sourceReadOk": True, "health": "degraded",
                  "cursor": {"next": "new"}, "messages": [self.event("new-1")],
                  "error": "thumbnail-backlog"}
        relay = runtime.Relay(self.config, self.db, lambda _request: result)
        relay.source_read_failed("connector-a")
        self.assertFalse(relay.scan_profile("primary"))
        self.assertEqual(json_cursor(self.db), runtime.compact({"next": "new"}))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)
        self.assertEqual(relay.source_failures["connector-a"], 0)

    def test_source_read_ok_false_or_missing_rejects_scan_payload(self):
        false_result = {"ok": False, "sourceReadOk": False, "health": "offline",
                        "cursor": {"next": "new"}, "messages": [self.event("ignored-false")]}
        relay = runtime.Relay(self.config, self.db, lambda _request: false_result)
        with self.assertRaises(runtime.SourceReadError):
            relay.scan_profile("primary")
        missing_result = {"ok": True, "health": "online", "cursor": {"next": "new"},
                          "messages": [self.event("ignored-missing")]}
        relay = runtime.Relay(self.config, self.db, lambda _request: missing_result)
        with self.assertRaisesRegex(RuntimeError, "invalid_scan_result"):
            relay.scan_profile("primary")
        self.assertIsNone(self.db.execute("SELECT value FROM cursors WHERE connector_id='connector-a' "
                                          "AND profile='primary'").fetchone())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)

    def test_repeated_source_read_failures_request_one_bounded_targeted_recovery(self):
        config = self.auto_wake_config()
        calls = []
        now = [1000.0]

        def adapter(request):
            calls.append(dict(request))
            if request["op"] == "ensure-active":
                return self.wake_result(False) if request.get("reason") else self.wake_result(True)
            raise OSError("native read unavailable")

        http_calls = []
        relay = runtime.Relay(config, self.db, adapter,
                              lambda method, path, payload=None: http_calls.append((method, path)) or
                                  {"ok": True, "commands": []})
        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]), patch.object(
            runtime.time, "time", side_effect=lambda: now[0]
        ):
            relay.pass_once()
            now[0] += 60
            relay.pass_once()
            now[0] += 15
            relay.pass_once()
            now[0] += 30
            relay.pass_once()
            recovery = [call for call in calls if call.get("reason") == "read_failure"]
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0], {"op": "ensure-active", "reason": "read_failure", "driver": "qq"})
            self.assertGreater(relay.source_settle_until["connector-a"], now[0])
            self.assertFalse(relay.health["connector-a"])
            self.assertEqual(relay.db.execute(
                "SELECT consecutive_failures FROM source_recovery WHERE connector_id='connector-a'"
            ).fetchone()[0], 3)
            self.assertGreater(relay.source_settle_until["connector-b"], now[0])
            self.assertFalse(relay.health["connector-b"])
            now[0] += 15
            relay.wake_ready = True
            relay.wake_ready_at = now[0]
            relay.wake_scan_pending = set(relay.connector_by_id)
            before = len([call for call in calls if call.get("op") == "scan"])
            http_calls.clear()
            relay.pass_once()
            self.assertEqual(len([call for call in calls if call.get("op") == "scan"]), before)
            self.assertFalse(any("/commands?" in path for _method, path in http_calls))

        self.db.close()
        db2 = runtime.open_database(self.db_path)
        try:
            recovery_calls = []
            restarted = runtime.Relay(config, db2,
                                      lambda request: recovery_calls.append(request) or self.wake_result(False),
                                      lambda *_args: {"ok": True})
            self.assertEqual(restarted.source_failures["connector-a"], 3)
            self.assertEqual(restarted.source_last_success["connector-a"], 0)
            self.assertGreater(restarted.source_recovery_after["connector-a"], now[0])
            self.assertGreater(restarted.source_settle_until["connector-a"], now[0])
            with patch.object(runtime.time, "time", return_value=1200.0):
                self.assertFalse(restarted.recover_source_after_failures("connector-a"))
            self.assertEqual(recovery_calls, [])
        finally:
            db2.close()
            self.db = sqlite3.connect(self.db_path)

    def test_successful_empty_native_read_resets_failure_streak(self):
        relay = runtime.Relay(self.config, self.db, lambda _request: {
            "ok": True, "sourceReadOk": True, "health": "online",
            "cursor": {"next": "same"}, "messages": []})
        relay.source_read_failed("connector-a")
        relay.source_read_failed("connector-a")
        self.assertTrue(relay.scan_profile("primary"))
        self.assertEqual(relay.source_failures["connector-a"], 0)
        self.assertEqual(relay.attach_failure_streak["connector-a"], (None, 0))

    def test_native_attach_failure_classification_requires_exact_safe_metadata(self):
        valid = {"stage": "attach", "errorCode": "attach_failed", "dispatch": "not_started", "processId": 12345}
        self.assertTrue(runtime.explicit_native_attach_failure(valid))
        self.assertTrue(runtime.explicit_native_attach_failure(
            {**valid, "errorCode": "timeout"}))
        for invalid in (
            None,
            {key: value for key, value in valid.items() if key != "processId"},
            {**valid, "processId": True},
            {**valid, "processId": 1},
            {**valid, "processId": 0},
            {**valid, "processId": -1},
            {**valid, "stage": "native-helper"},
            {**valid, "errorCode": "page_read_failed"},
            {**valid, "dispatch": "unknown"},
            {**valid, "detail": "ignored"},
        ):
            self.assertFalse(runtime.explicit_native_attach_failure(invalid))

        relay = runtime.Relay(self.config, self.db, lambda _request: {
            "ok": False, "sourceReadOk": False, "nativeFailure": valid})
        with self.assertRaises(runtime.SourceReadError) as caught:
            relay.scan_profile("primary")
        self.assertEqual(caught.exception.attach_failure_pid, 12345)

    def test_create_script_timeout_requires_exact_metadata_and_uses_same_pid_recovery(self):
        valid = {"stage": "create_script", "errorCode": "timeout",
                 "dispatch": "not_started", "processId": 12345}
        self.assertTrue(runtime.explicit_native_create_script_timeout(valid))
        for invalid in (
            None,
            {key: value for key, value in valid.items() if key != "processId"},
            {**valid, "processId": True},
            {**valid, "processId": 1},
            {**valid, "stage": "attach"},
            {**valid, "stage": "query_gate"},
            {**valid, "errorCode": "attach_failed"},
            {**valid, "dispatch": "unknown"},
            {**valid, "extra": "ignored"},
        ):
            self.assertFalse(runtime.explicit_native_create_script_timeout(invalid))

        config = self.auto_wake_config()
        config["connectors"] = config["connectors"][:1]
        requests = []
        response = {"ok": False, "sourceReadOk": False, "nativeFailure": valid}
        relay = runtime.Relay(config, self.db,
                              lambda request: requests.append(dict(request)) or
                              (self.wake_result(True) if request.get("op") == "ensure-active" else response))
        with self.assertRaises(runtime.SourceReadError) as caught:
            relay.scan_profile("primary")
        self.assertEqual(caught.exception.attach_failure_pid, 12345)
        self.assertIsNone(caught.exception.query_gate_pending_pid)

        relay.source_read_failed("connector-a", attach_failure_pid=12345)
        relay.source_read_failed("connector-a", attach_failure_pid=12345)
        self.assertFalse(relay.recover_attach_after_failures("connector-a"))
        relay.source_read_failed("connector-a", attach_failure_pid=12345)
        self.assertTrue(relay.recover_attach_after_failures("connector-a"))
        recoveries = [request for request in requests if request.get("op") == "ensure-active"]
        self.assertEqual(recoveries, [{"op": "ensure-active", "reason": "attach_failure",
                                       "driver": "qq", "observedPid": 12345}])

    def test_native_query_gate_classification_requires_exact_safe_metadata(self):
        valid = {"stage": "query_gate", "errorCode": "native-query-busy",
                 "dispatch": "not_started", "processId": 12345}
        self.assertTrue(runtime.explicit_native_query_gate_pending(valid))
        for invalid in (
            None,
            {key: value for key, value in valid.items() if key != "processId"},
            {**valid, "processId": True},
            {**valid, "processId": 1},
            {**valid, "stage": "attach"},
            {**valid, "errorCode": "timeout"},
            {**valid, "dispatch": "unknown"},
            {**valid, "extra": "ignored"},
        ):
            self.assertFalse(runtime.explicit_native_query_gate_pending(invalid))

        relay = runtime.Relay(self.config, self.db, lambda _request: {
            "ok": False, "sourceReadOk": False, "nativeFailure": valid})
        with self.assertRaises(runtime.SourceReadError) as caught:
            relay.scan_profile("primary")
        self.assertEqual(caught.exception.query_gate_pending_pid, 12345)
        self.assertIsNone(caught.exception.attach_failure_pid)

    def test_query_gate_streak_is_exact_same_pid_and_recovers_only_on_third(self):
        config = self.auto_wake_config()
        config["connectors"] = config["connectors"][:1]
        requests = []
        relay = runtime.Relay(config, self.db,
                              lambda request: requests.append(dict(request)) or self.wake_result(True))
        relay.source_read_failed("connector-a", query_gate_pending_pid=12345)
        relay.source_read_failed("connector-a", query_gate_pending_pid=12345)
        self.assertFalse(relay.recover_query_gate_after_failures("connector-a"))
        relay.source_read_failed("connector-a", query_gate_pending_pid=12346)
        self.assertEqual(relay.query_gate_failure_streak["connector-a"], (12346, 1))
        relay.source_read_failed("connector-a", query_gate_pending_pid=12346)
        self.assertFalse(relay.recover_query_gate_after_failures("connector-a"))
        relay.source_read_failed("connector-a", query_gate_pending_pid=12346)
        self.assertTrue(relay.recover_query_gate_after_failures("connector-a"))
        self.assertEqual(requests, [{"op": "ensure-active", "reason": "query_gate_pending",
                                     "driver": "qq", "observedPid": 12346}])
        self.assertEqual(relay.query_gate_failure_streak["connector-a"], (None, 0))
        for _ in range(3):
            relay.source_read_failed("connector-a", query_gate_pending_pid=12346)
        self.assertFalse(relay.recover_query_gate_after_failures("connector-a"))
        self.assertEqual(len(requests), 1)
        self.assertFalse(any(request.get("op") == "send" for request in requests))
        self.assertFalse(relay.ensure_active(
            recovery_driver="qq", recovery_reason="query_gate_pending", observed_pid=True))
        self.assertFalse(relay.ensure_active(
            recovery_driver="qq", recovery_reason="query_gate_pending", observed_pid=1))

    def test_non_gate_error_and_success_reset_query_gate_streak(self):
        failed_helper = runtime.Relay(self.config, self.db, lambda _request: (_ for _ in ()).throw(
            RuntimeError("native-helper-timeout")))
        with self.assertRaises(runtime.SourceReadError) as caught:
            failed_helper.scan_profile("primary")
        self.assertIsNone(caught.exception.query_gate_pending_pid)
        relay = runtime.Relay(self.config, self.db, lambda _request: {
            "ok": True, "sourceReadOk": True, "health": "online",
            "cursor": {"next": "same"}, "messages": []})
        relay.source_read_failed("connector-a", query_gate_pending_pid=12345)
        relay.source_read_failed("connector-a")
        self.assertEqual(relay.query_gate_failure_streak["connector-a"], (None, 0))
        relay.source_read_failed("connector-a", query_gate_pending_pid=12345)
        self.assertTrue(relay.scan_profile("primary"))
        self.assertEqual(relay.query_gate_failure_streak["connector-a"], (None, 0))

    def test_native_operation_uncertain_requires_exact_cleanup_metadata(self):
        valid = {"stage": "await_result", "errorCode": "timeout",
                 "cleanupCode": "cleanup_timeout", "cleanupStage": "unload",
                 "dispatch": "unknown", "processId": 12345}
        self.assertTrue(runtime.explicit_native_operation_uncertain(valid))
        self.assertFalse(runtime.explicit_native_operation_uncertain(
            {**valid, "cleanupIncomplete": True}))
        self.assertFalse(runtime.explicit_native_operation_uncertain(
            {**valid, "dispatch": "not_started"}))
        self.assertFalse(runtime.explicit_native_operation_uncertain(
            {**valid, "cleanupStage": "detach"}))

    def test_confirmed_cleanup_timeout_requires_bounded_ordered_phase_metadata(self):
        valid = {
            "stage": "cleanup", "errorCode": "cleanup_timeout",
            "cleanupCode": "cleanup_timeout", "cleanupStage": "unload",
            "cleanupIncomplete": False,
            "phaseElapsedMs": {"resultReceivedMs": 6440, "cleanupStartedMs": 6440,
                                "unloadFinishedMs": 11442, "detachFinishedMs": 11444,
                                "closeFinishedMs": 11444},
            "dispatch": "confirmed", "processId": 94058,
        }
        self.assertTrue(runtime.explicit_native_cleanup_operation_uncertain(valid))
        self.assertTrue(runtime.explicit_native_cleanup_operation_uncertain(
            {**valid, "cleanupIncomplete": True}))
        for invalid in (
            {**valid, "dispatch": "unknown"},
            {**valid, "phaseElapsedMs": {**valid["phaseElapsedMs"], "unloadFinishedMs": 11439}},
            {**valid, "phaseElapsedMs": {**valid["phaseElapsedMs"], "closeFinishedMs": 150001}},
            {**valid, "cleanupIncomplete": 0},
            {**valid, "errorCode": "timeout"},
        ):
            self.assertFalse(runtime.explicit_native_cleanup_operation_uncertain(invalid))

    def test_native_operation_state_survives_relay_restart(self):
        relay = runtime.Relay(self.auto_wake_config(), self.db,
                              lambda _request: {"ok": True, "commands": []})
        relay._block_native_operation("connector-a", 12345)
        restarted = runtime.Relay(self.auto_wake_config(), self.db,
                                  lambda _request: {"ok": True, "commands": []})
        self.assertEqual(restarted.native_operation_uncertain["connector-a"], 12345)
        restarted._clear_native_operation("connector-a")

    def test_native_operation_block_is_sent_to_qq_adapter(self):
        requests = []
        relay = runtime.Relay(self.config, self.db,
                              lambda request: requests.append(request) or {
                                  "ok": False, "sourceReadOk": False,
                                  "nativeFailure": {"stage": "native_operation",
                                      "errorCode": "blocked_pid", "dispatch": "not_started",
                                      "processId": 12345}})
        relay._block_native_operation("connector-a", 12345)
        with self.assertRaises(runtime.SourceReadError) as caught:
            relay.scan_profile("primary")
        self.assertEqual(caught.exception.native_operation_blocked_pid, 12345)
        self.assertEqual(requests[0]["blockedProcessId"], 12345)

    def test_confirmed_cleanup_failure_is_consumed_as_native_uncertain(self):
        failure = {
            "stage": "cleanup", "errorCode": "cleanup_timeout",
            "cleanupCode": "cleanup_timeout", "cleanupStage": "unload",
            "cleanupIncomplete": False,
            "phaseElapsedMs": {"resultReceivedMs": 6440, "cleanupStartedMs": 6440,
                                "unloadFinishedMs": 11442},
            "dispatch": "confirmed", "processId": 94058,
        }
        relay = runtime.Relay(
            self.config, self.db,
            lambda _request: {"ok": False, "sourceReadOk": False,
                               "nativeFailure": failure},
        )
        with self.assertRaises(runtime.SourceReadError) as caught:
            relay.scan_profile("primary")
        self.assertEqual(caught.exception.native_operation_uncertain_pid, 94058)

    def test_blocked_recovery_retries_after_cooldown(self):
        config = self.auto_wake_config()
        config["connectors"] = config["connectors"][:1]
        requests = []
        relay = runtime.Relay(config, self.db,
                              lambda request: requests.append(dict(request)) or self.wake_result(True))
        relay._block_native_operation("connector-a", 12345)
        relay.source_recovery_after["connector-a"] = runtime.time.time() + 300
        self.assertFalse(relay.recover_native_operation_after_uncertain("connector-a", 12345))
        relay.source_recovery_after["connector-a"] = 0
        self.assertTrue(relay.recover_native_operation_after_uncertain("connector-a", 12345))
        self.assertEqual(requests[-1], {"op": "ensure-active", "reason": "native_operation_uncertain",
                                        "driver": "qq", "observedPid": 12345})

    def test_corrupt_native_operation_state_fails_closed(self):
        relay = runtime.Relay(self.auto_wake_config(), self.db,
                              lambda _request: {"ok": True, "commands": []})
        with open(relay.native_operation_state_path, "w", encoding="utf-8") as stream:
            stream.write("not-json")
        restarted = runtime.Relay(self.auto_wake_config(), self.db,
                                  lambda _request: {"ok": True, "commands": []})
        self.assertTrue(restarted.native_operation_state_unavailable)
        with self.assertRaises(runtime.SourceReadError):
            restarted.scan_profile("primary")

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "mkfifo"),
                         "POSIX FIFO semantics required")
    def test_fifo_native_operation_state_fails_closed_without_blocking(self):
        relay = runtime.Relay(self.auto_wake_config(), self.db,
                              lambda _request: {"ok": True, "commands": []})
        os.mkfifo(relay.native_operation_state_path, 0o600)
        try:
            restarted = runtime.Relay(self.auto_wake_config(), self.db,
                                      lambda _request: {"ok": True, "commands": []})
            self.assertTrue(restarted.native_operation_state_unavailable)
            with self.assertRaises(runtime.SourceReadError):
                restarted.scan_profile("primary")
        finally:
            os.unlink(relay.native_operation_state_path)

    def test_native_operation_clear_persist_failure_keeps_quarantine_and_health(self):
        requests = []
        relay = runtime.Relay(self.config, self.db,
                              lambda request: requests.append(dict(request)) or {
                                  "ok": True, "sourceReadOk": True, "health": "online",
                                  "cursor": {"next": "same"}, "messages": []})
        relay._block_native_operation("connector-a", 12345)

        def failed_persist():
            relay.native_operation_state_unavailable = True
            return False
        relay._persist_native_operation_state = failed_persist

        with self.assertRaises(runtime.SourceReadError) as caught:
            relay.scan_profile("primary")
        self.assertEqual(str(caught.exception), "native_operation_state_persist_failed")
        self.assertFalse(relay.health["connector-a"])
        self.assertTrue(relay.native_operation_state_unavailable)
        self.assertEqual(relay.native_operation_uncertain["connector-a"], 12345)
        self.assertEqual(requests[0]["blockedProcessId"], 12345)

        with self.assertRaises(runtime.SourceReadError) as blocked:
            relay.scan_profile("primary")
        self.assertEqual(str(blocked.exception), "native_operation_state_unavailable")
        self.assertEqual(len(requests), 1)

    def test_changed_process_resets_attach_streak_and_requests_observed_pid(self):
        config = self.auto_wake_config()
        config["connectors"] = config["connectors"][:1]
        requests = []
        relay = runtime.Relay(config, self.db,
                              lambda request: requests.append(dict(request)) or self.wake_result(True))
        relay.source_read_failed("connector-a", attach_failure_pid=12345)
        relay.source_read_failed("connector-a", attach_failure_pid=12345)
        relay.source_read_failed("connector-a", attach_failure_pid=12346)
        self.assertEqual(relay.attach_failure_streak["connector-a"], (12346, 1))
        self.assertFalse(relay.recover_attach_after_failures("connector-a"))
        relay.source_read_failed("connector-a", attach_failure_pid=12346)
        relay.source_read_failed("connector-a", attach_failure_pid=12346)
        self.assertTrue(relay.recover_attach_after_failures("connector-a"))
        self.assertEqual(requests, [{"op": "ensure-active", "reason": "attach_failure",
                                    "driver": "qq", "observedPid": 12346}])

    def test_attach_recovery_rejects_pid_one(self):
        config = self.auto_wake_config()
        config["connectors"] = config["connectors"][:1]
        requests = []
        relay = runtime.Relay(config, self.db,
                              lambda request: requests.append(dict(request)) or self.wake_result(True))
        self.assertFalse(relay.ensure_active(
            recovery_driver="qq", recovery_reason="attach_failure", observed_pid=1))
        relay.source_read_failed("connector-a", attach_failure_pid=1)
        self.assertEqual(relay.attach_failure_streak["connector-a"], (None, 0))
        self.assertEqual(requests, [])

    def test_attach_failure_streak_requires_three_consecutive_failures_and_respects_cooldown(self):
        config = self.auto_wake_config()
        config["connectors"] = config["connectors"][:1]
        requests = []
        relay = runtime.Relay(config, self.db,
                              lambda request: requests.append(dict(request)) or self.wake_result(True))
        relay.source_read_failed("connector-a", attach_failure_pid=12345)
        relay.source_read_failed("connector-a", attach_failure_pid=12345)
        relay.source_read_failed("connector-a")
        self.assertEqual(relay.attach_failure_streak["connector-a"], (None, 0))
        relay.source_read_failed("connector-a", attach_failure_pid=12345)
        relay.source_read_failed("connector-a", attach_failure_pid=12345)
        self.assertFalse(relay.recover_attach_after_failures("connector-a"))
        relay.source_read_failed("connector-a", attach_failure_pid=12345)
        self.assertTrue(relay.recover_attach_after_failures("connector-a"))
        self.assertEqual(requests, [{"op": "ensure-active", "reason": "attach_failure",
                                    "driver": "qq", "observedPid": 12345}])
        self.assertFalse(relay.recover_attach_after_failures("connector-a"))

        self.db.execute(
            "INSERT INTO command_ledger(connector_id,idempotency_key,fingerprint,state,result,retryable) "
            "VALUES(?,?,?,?,?,?)",
            ("connector-a", "sent-unknown", "fingerprint", "done",
             runtime.compact({"uncertain": True, "error": "device_send_outcome_uncertain"}), 0),
        )
        self.db.commit()
        self.assertFalse(any(request.get("op") == "send" for request in requests))

    def test_attach_streak_does_not_survive_runtime_restart(self):
        config = self.auto_wake_config()
        config["connectors"] = config["connectors"][:1]
        requests = []
        relay = runtime.Relay(config, self.db,
                              lambda request: requests.append(dict(request)) or self.wake_result(True))
        relay.source_read_failed("connector-a", attach_failure_pid=12345)
        relay.source_read_failed("connector-a", attach_failure_pid=12345)
        relay.source_read_failed("connector-a", query_gate_pending_pid=12345)
        relay.source_read_failed("connector-a", query_gate_pending_pid=12345)
        self.assertEqual(relay.attach_failure_streak["connector-a"], (None, 0))
        self.assertEqual(relay.query_gate_failure_streak["connector-a"], (12345, 2))
        self.db.execute(
            "UPDATE source_recovery SET consecutive_failures=153 WHERE connector_id=?",
            ("connector-a",),
        )
        self.db.commit()
        self.db.close()
        restarted_db = runtime.open_database(self.db_path)
        try:
            restarted = runtime.Relay(config, restarted_db,
                                      lambda request: requests.append(dict(request)) or self.wake_result(True))
            self.assertEqual(restarted.source_failures["connector-a"], 153)
            self.assertEqual(restarted.attach_failure_streak["connector-a"], (None, 0))
            self.assertEqual(restarted.query_gate_failure_streak["connector-a"], (None, 0))
            self.assertFalse(restarted.recover_attach_after_failures("connector-a"))
            self.assertFalse(restarted.recover_query_gate_after_failures("connector-a"))
            restarted.source_read_failed("connector-a", query_gate_pending_pid=12345)
            restarted.source_read_failed("connector-a", query_gate_pending_pid=12345)
            self.assertFalse(restarted.recover_query_gate_after_failures("connector-a"))
            restarted.source_read_failed("connector-a", attach_failure_pid=12345)
            restarted.source_read_failed("connector-a", attach_failure_pid=12345)
            self.assertFalse(restarted.recover_attach_after_failures("connector-a"))
        finally:
            restarted_db.close()
            self.db = sqlite3.connect(self.db_path)

    def test_source_read_failure_logs_only_allowlisted_fields(self):
        relay = runtime.Relay(self.config, self.db, lambda _request: (_ for _ in ()).throw(
            RuntimeError("private-profile body target secret")),
            lambda *_args: {"ok": True, "commands": []})
        captured = io.StringIO()
        with redirect_stderr(captured):
            relay.pass_once()
        records = [json.loads(line) for line in captured.getvalue().splitlines()]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(set(record), {
            "observedAt", "driver", "consecutiveFailures", "classification", "processId",
        })
        self.assertEqual(record["driver"], "qq")
        self.assertEqual(record["consecutiveFailures"], 1)
        self.assertEqual(record["classification"], "source_unclassified")
        self.assertIsNone(record["processId"])
        self.assertTrue(record["observedAt"].endswith("Z"))
        self.assertNotIn("private-profile", captured.getvalue())
        self.assertNotIn("target", captured.getvalue())
        self.assertNotIn("secret", captured.getvalue())

    def test_source_read_failure_logs_explicit_query_gate_only_after_strict_validation(self):
        valid = {"stage": "query_gate", "errorCode": "native-query-busy",
                 "dispatch": "not_started", "processId": 12345}
        relay = runtime.Relay(self.config, self.db, lambda _request: {
            "ok": False, "sourceReadOk": False, "nativeFailure": valid},
            lambda *_args: {"ok": True, "commands": []})
        captured = io.StringIO()
        with redirect_stderr(captured):
            relay.pass_once()
        records = [json.loads(line) for line in captured.getvalue().splitlines()]
        record = next(item for item in records if "classification" in item)
        self.assertEqual(record["classification"], "explicit_query_gate")
        self.assertEqual(record["processId"], 12345)
        self.assertEqual(record["consecutiveFailures"], 1)

        invalid = {**valid, "dispatch": "unknown"}
        relay = runtime.Relay(self.config, self.db, lambda _request: {
            "ok": False, "sourceReadOk": False, "nativeFailure": invalid},
            lambda *_args: {"ok": True, "commands": []})
        captured = io.StringIO()
        with redirect_stderr(captured):
            relay.pass_once()
        records = [json.loads(line) for line in captured.getvalue().splitlines()]
        record = next(item for item in records if "classification" in item)
        self.assertEqual(record["classification"], "source_unclassified")
        self.assertIsNone(record["processId"])

    def test_source_read_failure_logs_explicit_attach_only_after_strict_validation(self):
        valid = {"stage": "attach", "errorCode": "timeout",
                 "dispatch": "not_started", "processId": 12345}
        relay = runtime.Relay(self.config, self.db, lambda _request: {
            "ok": False, "sourceReadOk": False,
            "nativeFailure": {**valid, "detail": "private target body"},
        }, lambda *_args: {"ok": True, "commands": []})
        captured = io.StringIO()
        with redirect_stderr(captured):
            relay.pass_once()
        record = json.loads(captured.getvalue())
        self.assertEqual(set(record), {
            "observedAt", "driver", "consecutiveFailures", "classification", "processId",
        })
        self.assertEqual(record["classification"], "source_unclassified")
        self.assertIsNone(record["processId"])
        self.assertNotIn("private", captured.getvalue())

        valid_db = runtime.open_database(os.path.join(self.temp.name, "valid.sqlite3"))
        try:
            relay = runtime.Relay(self.config, valid_db, lambda _request: {
                "ok": False, "sourceReadOk": False, "nativeFailure": valid,
            }, lambda *_args: {"ok": True, "commands": []})
            captured = io.StringIO()
            with redirect_stderr(captured):
                relay.pass_once()
            record = json.loads(captured.getvalue())
            self.assertEqual(record["classification"], "explicit_attach")
            self.assertEqual(record["processId"], 12345)
        finally:
            valid_db.close()

    def test_stderr_failure_does_not_interrupt_attach_recovery_threshold(self):
        config = self.auto_wake_config()
        config["connectors"] = config["connectors"][:1]
        requests = []
        valid_failure = {"stage": "attach", "errorCode": "timeout",
                         "dispatch": "not_started", "processId": 12345}

        def adapter(request):
            requests.append(dict(request))
            if request["op"] == "ensure-active":
                return self.wake_result(True)
            return {"ok": False, "sourceReadOk": False, "nativeFailure": valid_failure}

        relay = runtime.Relay(config, self.db, adapter,
                              lambda *_args: {"ok": True, "commands": []})
        relay.wake_ready = True
        relay.wake_readiness_established = True
        relay.wake_ready_at = 100
        relay.last_wake_attempt = 0
        relay.last_logged_wake_state = (True, False, "ready")
        relay.source_settle_until["connector-a"] = 0

        class BrokenStderr:
            def write(self, _value):
                raise OSError("stream unavailable")

            def flush(self):
                raise OSError("stream unavailable")

        now = [100.0]
        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]), patch.object(
                runtime.time, "time", side_effect=lambda: now[0]), patch.object(
                    runtime.sys, "stderr", BrokenStderr()):
            for scan_time in (100.0, 116.0, 147.0):
                now[0] = scan_time
                relay.pass_once()

        recoveries = [request for request in requests
                      if request.get("op") == "ensure-active" and request.get("reason")]
        self.assertEqual(recoveries, [{"op": "ensure-active", "reason": "attach_failure",
                                      "driver": "qq", "observedPid": 12345}])
        self.assertEqual(relay.attach_failure_streak["connector-a"], (12345, 3))

    def test_backpressure_skip_does_not_refresh_scan_health_or_clear_forced_scan(self):
        relay = runtime.Relay(self.auto_wake_config(), self.db,
                              lambda _request: self.wake_result(True),
                              lambda *_args: {"ok": True, "commands": []})
        relay.wake_ready = True
        relay.wake_readiness_established = True
        relay.wake_ready_at = 1000
        relay.last_wake_attempt = 990
        relay.health.update({"connector-a": True, "connector-b": True})
        relay.last_scan.update({"connector-a": 990, "connector-b": 990})
        relay.wake_scan_pending = set(relay.connector_by_id)
        relay.wake_scan_failures["connector-a"] = 2
        relay.wake_scan_retry_at["connector-a"] = 5000
        with patch.object(runtime.time, "monotonic", return_value=1000), patch.object(
            runtime.time, "time", return_value=1000
        ), patch.object(relay, "scan_profile", return_value=None) as scan:
            relay.pass_once()
        self.assertEqual(scan.call_count, 2)
        self.assertEqual(relay.last_scan, {"connector-a": 990, "connector-b": 990})
        self.assertEqual(relay.health, {"connector-a": True, "connector-b": True})
        self.assertEqual(relay.wake_scan_failures["connector-a"], 2)
        self.assertEqual(relay.wake_scan_pending, {"connector-a", "connector-b"})

    def test_startup_settle_suppresses_scan_and_command_poll(self):
        config = self.auto_wake_config()
        http_calls = []
        relay = runtime.Relay(config, self.db,
                              lambda _request: self.wake_result(True),
                              lambda method, path, payload=None: http_calls.append((method, path)) or
                                  {"ok": True, "commands": []})
        relay.ensure_active = lambda: True
        relay.wake_ready = True
        relay.wake_readiness_established = True
        relay.wake_ready_at = 1000
        relay.health.update({connector_id: True for connector_id in relay.connector_by_id})
        relay.last_scan.update({connector_id: 990 for connector_id in relay.connector_by_id})
        relay.source_settle_until.update({connector_id: 1100 for connector_id in relay.connector_by_id})
        with patch.object(runtime.time, "monotonic", return_value=1000), patch.object(
            runtime.time, "time", return_value=1000
        ), patch.object(relay, "scan_profile") as scan:
            relay.pass_once()
        scan.assert_not_called()
        self.assertFalse(any("/commands?" in path for _method, path in http_calls))

    def test_sender_avatar_sync_failure_preserves_cursor_and_outbox(self):
        result = {"ok": True, "sourceReadOk": True, "health": "online", "cursor": {"next": "2"},
                  "messages": [self.event("new-1")], "senderAvatars": [{"senderId": "sender-1"}]}
        relay = runtime.Relay(self.config, self.db, lambda _: result)
        with patch.object(runtime, "sync_profiles", return_value=0), patch.object(
            runtime, "sync_sender_avatars", side_effect=RuntimeError("offline")
        ) as sync_avatars:
            with self.assertRaisesRegex(RuntimeError, "offline"):
                relay.scan_profile("primary")
        sync_avatars.assert_called_once_with(relay, result["senderAvatars"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM cursors").fetchone()[0], 0)

        with patch.object(runtime, "sync_profiles", return_value=0), patch.object(
            runtime, "sync_sender_avatars", return_value=1
        ) as sync_avatars:
            relay.scan_profile("primary")
        sync_avatars.assert_called_once_with(relay, result["senderAvatars"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM cursors").fetchone()[0], 1)

    def test_offline_spool_survives_restart_and_response_loss_reuses_event_id(self):
        calls = []
        def scan(_request):
            return {"ok": True, "sourceReadOk": True, "health": "online", "cursor": {"next": "2"},
                    "messages": [self.event("stable-1")]}
        def lose_response(method, path, payload=None):
            calls.append((method, path, payload))
            if path.endswith("/events"):
                raise OSError("connection lost after request")
            return {"ok": True}
        first = runtime.Relay(self.config, self.db, scan, lose_response)
        first.scan_profile("primary")
        self.assertFalse(first.flush_one())
        saved = self.db.execute("SELECT external_id FROM outbox").fetchone()[0]
        self.assertEqual(saved, "stable-1")
        self.db.close()

        db2 = runtime.open_database(self.db_path)
        try:
            success_calls = []
            relay = runtime.Relay(self.config, db2, scan,
                                  lambda method, path, payload=None: success_calls.append(payload) or
                                      self.event_ack(len(payload["messages"]), inserted=0))
            relay.flush_one()
            self.assertEqual(success_calls[0]["messages"][0]["externalId"], "stable-1")
            self.assertEqual(db2.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)
        finally:
            db2.close()
            self.db = sqlite3.connect(self.db_path)

    def test_full_outbox_does_not_commit_source_cursor(self):
        old = runtime.compact({"next": "old"})
        self.db.execute("INSERT INTO cursors(connector_id,profile,value) VALUES('connector-a','primary',?)", (old,))
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES('connector-a','primary','existing','{}',99)")
        self.db.commit()
        self.config["outboxMaxBytes"] = 99
        calls = []
        relay = runtime.Relay(self.config, self.db,
                              lambda req: calls.append(req) or {"ok": True, "sourceReadOk": True, "health": "online",
                                  "cursor": {"next": "new"}, "messages": [self.event("next")]},
                              lambda *args: {"ok": True})
        self.assertFalse(relay.scan_profile("primary"))
        self.assertEqual(json_cursor(self.db), old)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)

    def test_full_pending_outbox_still_stops_pass_scan_without_advancing_cursor(self):
        old = runtime.compact({"next": "old"})
        self.db.execute(
            "INSERT INTO cursors(connector_id,profile,value) VALUES('connector-a','primary',?)", (old,))
        self.db.execute(
            "INSERT INTO outbox(connector_id,profile,external_id,body,size) "
            "VALUES('connector-a','primary','existing','{}',99)")
        self.db.commit()
        self.config["outboxMaxBytes"] = 99
        scans = []
        relay = runtime.Relay(
            self.config, self.db,
            lambda request: scans.append(request) or {
                "ok": True, "sourceReadOk": True, "health": "online",
                "cursor": {"next": "new"}, "messages": [self.event("would-overflow")],
            },
            lambda *args: {"ok": True},
        )

        relay.pass_once()

        self.assertEqual(scans, [])
        self.assertEqual(json_cursor(self.db), old)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)

    def test_scan_passes_selected_connector_kind_as_explicit_driver(self):
        captured = []
        relay = runtime.Relay(
            self.config, self.db,
            lambda request: captured.append(request) or {
                "ok": True, "sourceReadOk": True, "health": "online", "active": False,
                "cursor": None, "messages": [],
            },
        )
        relay.scan_profile("primary")
        self.assertEqual(captured[0]["driver"], "qq")
        self.config["connectors"][0]["kind"] = "wechat"
        relay.scan_profile("primary")
        self.assertEqual(captured[1]["driver"], "wechat")

    def test_default_relay_adapter_uses_scan_operation_deadline(self):
        result = {"ok": True, "sourceReadOk": True, "health": "online", "active": False,
                  "cursor": None, "messages": []}
        with patch.object(runtime, "run_adapter", return_value=result) as run:
            relay = runtime.Relay(self.config, self.db)
            relay.scan_profile("primary")
        request = run.call_args.args[1]
        self.assertEqual(request["op"], "scan")
        self.assertEqual(run.call_args.kwargs["timeout"], runtime.ADAPTER_SCAN_TIMEOUT)
        self.assertEqual(runtime.ADAPTER_SCAN_TIMEOUT, 60)

    def test_send_adapter_timeout_covers_private_deadline_and_remains_uncertain(self):
        self.save_cursor()
        command = {"id": "command-timeout", "leaseToken": "lease-timeout",
                   "idempotencyKey": "key-timeout",
                   "payload": {"externalConversationId": "conversation-aaaaaaaa",
                               "body": "synthetic"}}
        with patch.object(runtime, "run_adapter", side_effect=RuntimeError("adapter_timeout")) as run:
            relay = runtime.Relay(
                self.config, self.db,
                http_call=lambda method, path, payload=None: {"ok": True},
            )
            relay.process_command(command, "primary")
        request = run.call_args.args[1]
        self.assertEqual(request["op"], "send")
        self.assertEqual(run.call_args.kwargs["timeout"], runtime.ADAPTER_SEND_TIMEOUT)
        self.assertEqual(runtime.ADAPTER_SEND_TIMEOUT, 130)
        state, result, retryable = self.db.execute(
            "SELECT state,result,retryable FROM command_ledger WHERE connector_id=? AND idempotency_key=?",
            ("connector-a", "key-timeout"),
        ).fetchone()
        self.assertEqual(state, "done")
        self.assertEqual(json.loads(result), {"uncertain": True, "error": "device_send_outcome_uncertain"})
        self.assertEqual(retryable, 0)

    def test_native_operation_block_quarantines_qq_send_before_adapter(self):
        command = {"id": "command-blocked", "leaseToken": "lease-blocked",
                   "idempotencyKey": "key-blocked",
                   "payload": {"externalConversationId": "conversation-aaaaaaaa",
                               "body": "blocked"}}
        calls = []
        relay = runtime.Relay(
            self.config, self.db,
            lambda request: calls.append(request),
            http_call=lambda method, path, payload=None: {"ok": True},
        )
        relay._block_native_operation("connector-a", 94058)
        relay.process_command(command, "primary")
        self.assertEqual(calls, [])
        state, result, retryable = self.db.execute(
            "SELECT state,result,retryable FROM command_ledger WHERE connector_id=? AND idempotency_key=?",
            ("connector-a", "key-blocked"),
        ).fetchone()
        self.assertEqual(state, "retry")
        self.assertEqual(json.loads(result), {
            "retry": True, "dispatched": False, "error": "native_operation_uncertain"})
        self.assertEqual(retryable, 1)

    def test_pre_dispatch_retry_survives_restart_then_stops_on_terminal_rejection(self):
        self.save_cursor()
        command = {"id": "command-retry", "leaseToken": "lease-retry",
                   "idempotencyKey": "key-retry",
                   "payload": {"externalConversationId": "conversation-aaaaaaaa",
                               "body": "synthetic"}}
        def http_call(method, path, payload=None):
            return {"ok": True}
        first = runtime.Relay(self.config, self.db, lambda request: {
            "ok": False, "dispatched": False, "retryable": True,
            "error": "temporarily-unavailable"}, http_call=http_call)
        first.process_command(command, "primary")
        state, raw, retryable = self.db.execute(
            "SELECT state,result,retryable FROM command_ledger WHERE idempotency_key=?",
            ("key-retry",)).fetchone()
        self.assertEqual((state, retryable), ("retry", 1))
        self.assertEqual(json.loads(raw), {"retry": True, "error": "temporarily-unavailable"})
        calls = []
        def terminal_adapter(request):
            calls.append(request)
            return {"ok": False, "dispatched": False, "retryable": False,
                    "error": "target-context-unverified"}
        restarted = runtime.Relay(self.config, self.db, terminal_adapter, http_call=http_call)
        restarted.process_command(command, "primary")
        restarted.process_command(command, "primary")
        self.assertEqual(len(calls), 1)
        state, raw, retryable = self.db.execute(
            "SELECT state,result,retryable FROM command_ledger WHERE idempotency_key=?",
            ("key-retry",)).fetchone()
        self.assertEqual((state, retryable), ("done", 0))
        self.assertEqual(json.loads(raw), {"ok": False, "error": "target-context-unverified"})

    def test_attachment_without_staging_contract_does_not_commit_cursor(self):
        old = runtime.compact({"next": "old"})
        self.db.execute("INSERT INTO cursors(connector_id,profile,value) VALUES('connector-a','primary',?)", (old,))
        self.db.commit()
        relay = runtime.Relay(self.config, self.db,
                              lambda req: {"ok": True, "sourceReadOk": True, "health": "online", "cursor": {"next": "new"},
                                           "messages": [dict(self.event("file"), attachments=[{"externalId": "f"}])]},
                              lambda *args: {"ok": True})
        with self.assertRaisesRegex(RuntimeError, "invalid_staging_key"):
            relay.scan_profile("primary")
        self.assertEqual(json_cursor(self.db), old)

    def test_image_scan_stages_bounded_metadata_and_upload_precedes_ack(self):
        media_root = os.path.join(self.temp.name, "media")
        media_dir = os.path.join(media_root, "connector-a")
        os.makedirs(media_dir)
        payload = b"image-data" * 9000
        with open(os.path.join(media_dir, "image-one.bin"), "wb") as staged:
            staged.write(payload)
        media_hash = runtime.hashlib.sha256(payload).hexdigest()
        attachment = {"externalId": "file-one", "fileName": "photo.png", "mimeType": "image/png",
                      "sizeBytes": len(payload), "sha256": media_hash, "stagingKey": "image-one.bin"}
        request_seen = []
        event = dict(self.event("group-image"), conversationType="group", trigger="background",
                      body="", attachments=[attachment])
        relay = runtime.Relay(self.config, self.db,
                              lambda request: request_seen.append(request) or {
                                  "ok": True, "sourceReadOk": True, "health": "online", "cursor": {"n": 1},
                                  "messages": [event]},
                              lambda *args: {"ok": True, "received": 1})
        relay.media_directory = media_root
        self.assertTrue(relay.scan_profile("primary"))
        self.assertEqual(request_seen[0]["mediaDirectory"], media_dir)
        self.assertEqual(request_seen[0]["maxMediaBytes"], 100000)
        row = self.db.execute("SELECT body,size FROM outbox WHERE external_id='group-image'").fetchone()
        saved = __import__("json").loads(row[0])
        self.assertEqual(saved["body"], "[图片]")
        self.assertEqual(row[1], len(runtime.compact({"connectorId": "connector-a", "messages": [saved]}).encode()) + len(payload))
        uploaded = []
        relay.upload_attachment = lambda message, item: uploaded.append((message["externalId"], item["externalId"]))
        delivered = []
        relay.http_call = lambda method, path, body=None: delivered.append((path, body)) or self.backup_ack(1)
        self.assertTrue(relay.flush_one())
        self.assertEqual(uploaded, [("group-image", "file-one")])
        cloud_attachment = delivered[0][1]["messages"][0]["attachments"][0]
        self.assertNotIn("stagingKey", cloud_attachment)
        self.assertFalse(os.path.exists(os.path.join(media_dir, "image-one.bin")))

    def test_same_event_late_attachment_enriches_existing_outbox_row(self):
        media_root = os.path.join(self.temp.name, "media")
        media_dir = os.path.join(media_root, "connector-a")
        os.makedirs(media_dir)
        payload = b"late-image-bytes"
        with open(os.path.join(media_dir, "late-image.bin"), "wb") as staged:
            staged.write(payload)
        attachment = {"externalId": "file-late", "fileName": "late.png", "mimeType": "image/png",
                      "sizeBytes": len(payload), "sha256": runtime.hashlib.sha256(payload).hexdigest(),
                      "stagingKey": "late-image.bin"}
        placeholder = dict(self.event("late-media"), contentType="text", attachments=[])
        enriched = dict(placeholder, contentType="mixed", attachments=[attachment])
        current = {"event": placeholder, "cursor": {"n": 1}}
        relay = runtime.Relay(self.config, self.db,
                              lambda _request: {"ok": True, "sourceReadOk": True, "health": "online",
                                  "cursor": current["cursor"], "messages": [current["event"]]},
                              lambda *_args: {"ok": True})
        relay.media_directory = media_root
        self.assertTrue(relay.scan_profile("primary"))
        old_row = self.db.execute("SELECT seq,body,size FROM outbox WHERE external_id='late-media'").fetchone()
        self.assertEqual(json.loads(old_row[1])["attachments"], [])
        self.assertEqual(json_cursor(self.db), runtime.compact({"n": 1}))

        current["event"] = enriched
        current["cursor"] = {"n": 2}
        self.assertTrue(relay.scan_profile("primary"))
        new_row = self.db.execute("SELECT seq,body,size FROM outbox WHERE external_id='late-media'").fetchone()
        self.assertEqual(new_row[0], old_row[0])
        saved = json.loads(new_row[1])
        self.assertEqual(saved["contentType"], "mixed")
        self.assertEqual(saved["attachments"], [attachment])
        expected_size = len(runtime.compact({"connectorId": "connector-a", "messages": [saved]}).encode()) + len(payload)
        self.assertEqual(new_row[2], expected_size)
        self.assertEqual(json_cursor(self.db), runtime.compact({"n": 2}))

    def test_late_attachment_conflict_and_invalid_staging_leave_placeholder_and_cursor(self):
        media_root = os.path.join(self.temp.name, "media")
        media_dir = os.path.join(media_root, "connector-a")
        os.makedirs(media_dir)
        payload = b"late-image-bytes"
        with open(os.path.join(media_dir, "late-image.bin"), "wb") as staged:
            staged.write(payload)
        attachment = {"externalId": "file-late", "fileName": "late.png", "mimeType": "image/png",
                      "sizeBytes": len(payload), "sha256": runtime.hashlib.sha256(payload).hexdigest(),
                      "stagingKey": "late-image.bin"}
        placeholder = dict(self.event("late-media"), contentType="text")
        enriched = dict(placeholder, contentType="mixed", attachments=[attachment])
        current = {"event": placeholder, "cursor": {"n": 1}}
        relay = runtime.Relay(self.config, self.db,
                              lambda _request: {"ok": True, "sourceReadOk": True, "health": "online",
                                  "cursor": current["cursor"], "messages": [current["event"]]},
                              lambda *_args: {"ok": True})
        relay.media_directory = media_root
        relay.scan_profile("primary")
        old_row = self.db.execute("SELECT seq,body,size FROM outbox WHERE external_id='late-media'").fetchone()
        old_cursor = json_cursor(self.db)

        current["event"] = dict(enriched, senderName="Other")
        current["cursor"] = {"n": 2}
        with self.assertRaisesRegex(RuntimeError, "event_id_conflict_in_outbox"):
            relay.scan_profile("primary")
        self.assertEqual(self.db.execute("SELECT seq,body,size FROM outbox WHERE external_id='late-media'").fetchone(), old_row)
        self.assertEqual(json_cursor(self.db), old_cursor)

        current["event"] = dict(enriched, contentType="text")
        with self.assertRaisesRegex(RuntimeError, "event_id_conflict_in_outbox"):
            relay.scan_profile("primary")
        self.assertEqual(self.db.execute("SELECT seq,body,size FROM outbox WHERE external_id='late-media'").fetchone(), old_row)
        self.assertEqual(json_cursor(self.db), old_cursor)

        current["event"] = dict(enriched, attachments=[dict(attachment, stagingKey="missing.bin")])
        with self.assertRaisesRegex(RuntimeError, "staged_file_missing"):
            relay.scan_profile("primary")
        self.assertEqual(self.db.execute("SELECT seq,body,size FROM outbox WHERE external_id='late-media'").fetchone(), old_row)
        self.assertEqual(json_cursor(self.db), old_cursor)

    def test_late_attachment_byte_budget_uses_size_delta_and_rolls_back_cursor(self):
        media_root = os.path.join(self.temp.name, "media")
        media_dir = os.path.join(media_root, "connector-a")
        os.makedirs(media_dir)
        payload = b"late-image-bytes"
        with open(os.path.join(media_dir, "late-image.bin"), "wb") as staged:
            staged.write(payload)
        attachment = {"externalId": "file-late", "fileName": "late.png", "mimeType": "image/png",
                      "sizeBytes": len(payload), "sha256": runtime.hashlib.sha256(payload).hexdigest(),
                      "stagingKey": "late-image.bin"}
        placeholder = dict(self.event("late-media"), contentType="text")
        enriched = dict(placeholder, contentType="mixed", attachments=[attachment])
        current = {"event": placeholder, "cursor": {"n": 1}}
        relay = runtime.Relay(self.config, self.db,
                              lambda _request: {"ok": True, "sourceReadOk": True, "health": "online",
                                  "cursor": current["cursor"], "messages": [current["event"]]},
                              lambda *_args: {"ok": True})
        relay.media_directory = media_root
        relay.scan_profile("primary")
        old_row = self.db.execute("SELECT seq,body,size FROM outbox WHERE external_id='late-media'").fetchone()
        old_cursor = json_cursor(self.db)
        new_size = len(runtime.compact({"connectorId": "connector-a", "messages": [enriched]}).encode()) + len(payload)
        self.assertGreater(new_size, old_row[2])
        self.config["outboxMaxBytes"] = new_size - 1
        current["event"] = enriched
        current["cursor"] = {"n": 2}

        self.assertIsNone(relay.scan_profile("primary"))
        self.assertEqual(self.db.execute("SELECT seq,body,size FROM outbox WHERE external_id='late-media'").fetchone(), old_row)
        self.assertEqual(json_cursor(self.db), old_cursor)

    def test_late_attachment_update_rolls_back_when_cursor_commit_fails(self):
        media_root = os.path.join(self.temp.name, "media")
        media_dir = os.path.join(media_root, "connector-a")
        os.makedirs(media_dir)
        payload = b"late-image-bytes"
        with open(os.path.join(media_dir, "late-image.bin"), "wb") as staged:
            staged.write(payload)
        attachment = {"externalId": "file-late", "fileName": "late.png", "mimeType": "image/png",
                      "sizeBytes": len(payload), "sha256": runtime.hashlib.sha256(payload).hexdigest(),
                      "stagingKey": "late-image.bin"}
        placeholder = dict(self.event("late-media"), contentType="text")
        enriched = dict(placeholder, contentType="mixed", attachments=[attachment])
        current = {"event": placeholder, "cursor": {"n": 1}}
        relay = runtime.Relay(self.config, self.db,
                              lambda _request: {"ok": True, "sourceReadOk": True, "health": "online",
                                  "cursor": current["cursor"], "messages": [current["event"]]},
                              lambda *_args: {"ok": True})
        relay.media_directory = media_root
        relay.scan_profile("primary")
        old_row = self.db.execute("SELECT seq,body,size FROM outbox WHERE external_id='late-media'").fetchone()
        old_cursor = json_cursor(self.db)
        self.db.execute("CREATE TRIGGER fail_cursor_update BEFORE UPDATE ON cursors "
                        "BEGIN SELECT RAISE(ABORT, 'cursor write failed'); END")
        self.db.commit()
        current["event"] = enriched
        current["cursor"] = {"n": 2}

        with self.assertRaises(sqlite3.IntegrityError):
            relay.scan_profile("primary")
        self.assertEqual(self.db.execute("SELECT seq,body,size FROM outbox WHERE external_id='late-media'").fetchone(), old_row)
        self.assertEqual(json_cursor(self.db), old_cursor)

    def test_connector_media_directories_isolate_same_staging_key_and_cleanup(self):
        second = dict(self.config["connectors"][0], id="connector-b", token="y" * 40, profile="secondary")
        self.config["connectors"].append(second)
        relay = runtime.Relay(self.config, self.db, lambda _request: {}, lambda *_args: {"ok": True})
        first_directory = relay.media_directory_for("connector-a")
        second_directory = relay.media_directory_for("connector-b")
        first_bytes = b"first-file"
        second_bytes = b"second-file"
        for directory, payload in ((first_directory, first_bytes), (second_directory, second_bytes)):
            with open(os.path.join(directory, "same-name"), "wb") as staged:
                staged.write(payload)
            with open(os.path.join(directory, "orphan"), "wb") as staged:
                staged.write(b"orphan")
        self.assertNotEqual(first_directory, second_directory)
        first_attachment = {"externalId": "file-a", "fileName": "a.png", "mimeType": "image/png",
                            "sizeBytes": len(first_bytes), "sha256": runtime.hashlib.sha256(first_bytes).hexdigest(),
                            "stagingKey": "same-name"}
        second_attachment = {"externalId": "file-b", "fileName": "b.png", "mimeType": "image/png",
                             "sizeBytes": len(second_bytes), "sha256": runtime.hashlib.sha256(second_bytes).hexdigest(),
                             "stagingKey": "same-name"}
        relay.select_connector(self.config["connectors"][0])
        self.assertEqual(relay.validate_staged_attachment(first_attachment)["sha256"], first_attachment["sha256"])
        relay.select_connector(second)
        self.assertEqual(relay.validate_staged_attachment(second_attachment)["sha256"], second_attachment["sha256"])
        for connector_id, attachment in (("connector-a", first_attachment), ("connector-b", second_attachment)):
            body = runtime.compact({"attachments": [attachment]})
            self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,?)",
                            (connector_id, "primary", "message-" + connector_id, body, 1))
        self.db.commit()
        relay.cleanup_unreferenced_media()
        self.assertTrue(os.path.exists(os.path.join(first_directory, "same-name")))
        self.assertTrue(os.path.exists(os.path.join(second_directory, "same-name")))
        self.assertFalse(os.path.exists(os.path.join(first_directory, "orphan")))
        self.assertFalse(os.path.exists(os.path.join(second_directory, "orphan")))

    def test_image_upload_failure_keeps_outbox_and_staged_bytes_for_retry(self):
        media_root = os.path.join(self.temp.name, "media")
        media_dir = os.path.join(media_root, "connector-a")
        os.makedirs(media_dir)
        payload = b"image"
        with open(os.path.join(media_dir, "image-retry.bin"), "wb") as staged:
            staged.write(payload)
        attachment = {"externalId": "file-retry", "fileName": "photo.png", "mimeType": "image/png",
                      "sizeBytes": len(payload), "sha256": runtime.hashlib.sha256(payload).hexdigest(),
                      "stagingKey": "image-retry.bin"}
        message = dict(self.event("retry-image"), attachments=[attachment])
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,?)",
                        ("connector-a", "primary", "retry-image", runtime.compact(message), 500))
        self.db.commit()
        relay = runtime.Relay(self.config, self.db, lambda req: {}, lambda *args: {"ok": True})
        relay.media_directory = media_root
        relay.upload_attachment = lambda *_args: (_ for _ in ()).throw(OSError("upload response lost"))
        self.assertFalse(relay.flush_one())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox WHERE external_id='retry-image'").fetchone()[0], 1)
        self.assertTrue(os.path.exists(os.path.join(media_dir, "image-retry.bin")))

    def test_invalid_staged_image_metadata_freezes_cursor(self):
        media_root = os.path.join(self.temp.name, "media")
        media_dir = os.path.join(media_root, "connector-a")
        os.makedirs(media_dir)
        message = dict(self.event("unsafe-image"), attachments=[{
            "externalId": "file-unsafe", "fileName": "photo.png", "mimeType": "image/png",
            "sizeBytes": 1, "sha256": "0" * 64, "stagingKey": "../escape.png"}])
        relay = runtime.Relay(self.config, self.db,
                              lambda req: {"ok": True, "sourceReadOk": True, "health": "online", "cursor": {"n": 1},
                                           "messages": [message]}, lambda *args: {"ok": True})
        relay.media_directory = media_root
        with self.assertRaisesRegex(RuntimeError, "invalid_staging_key"):
            relay.scan_profile("primary")
        self.assertIsNone(self.db.execute("SELECT value FROM cursors").fetchone())

    def test_https_image_upload_sends_fixed_size_chunks_and_idempotency_headers(self):
        media_root = os.path.join(self.temp.name, "media")
        media_dir = os.path.join(media_root, "connector-a")
        os.makedirs(media_dir)
        payload = b"z" * (runtime.MEDIA_CHUNK * 2 + 13)
        with open(os.path.join(media_dir, "upload.bin"), "wb") as staged:
            staged.write(payload)
        attachment = {"externalId": "file-id-1", "fileName": "photo one.png", "mimeType": "image/png",
                      "sizeBytes": len(payload), "sha256": runtime.hashlib.sha256(payload).hexdigest(),
                      "stagingKey": "upload.bin"}
        sent = {"chunks": [], "headers": [], "request": None}

        class Response:
            status = 200
            def read(self, _limit):
                return b'{"ok":true,"fileId":"file-id-1"}'

        class Connection:
            def __init__(self, host, port, timeout):
                sent["host_port_timeout"] = (host, port, timeout)
            def putrequest(self, method, path):
                sent["request"] = (method, path)
            def putheader(self, name, value):
                sent["headers"].append((name.lower(), value))
            def endheaders(self):
                pass
            def send(self, chunk):
                sent["chunks"].append(bytes(chunk))
            def getresponse(self):
                return Response()
            def close(self):
                pass

        relay = runtime.Relay(self.config, self.db, lambda req: {}, lambda *args: {"ok": True})
        relay.media_directory = media_root
        relay.select_connector(self.config["connectors"][0])
        with patch.object(runtime.http.client, "HTTPSConnection", Connection):
            result = relay.upload_attachment({"conversationExternalId": "conversation-1"}, attachment)
        self.assertTrue(result["ok"])
        self.assertEqual(sent["request"], ("PUT", "/api/connectors/files/file-id-1"))
        self.assertEqual(max(map(len, sent["chunks"])), runtime.MEDIA_CHUNK)
        self.assertEqual(b"".join(sent["chunks"]), payload)
        headers = dict(sent["headers"])
        self.assertEqual(headers["content-length"], str(len(payload)))
        self.assertEqual(headers["x-file-external-id"], "file-id-1")
        self.assertEqual(headers["x-conversation-id"], "conversation-1")
        self.assertEqual(headers["x-file-name"], "photo%20one.png")
        self.assertEqual(headers["x-content-sha256"], attachment["sha256"])

    def test_database_write_failure_rolls_back_spool_and_cursor(self):
        old = runtime.compact({"next": "old"})
        self.db.execute("INSERT INTO cursors(connector_id,profile,value) VALUES('connector-a','primary',?)", (old,))
        self.db.execute("CREATE TRIGGER fail_cursor BEFORE UPDATE ON cursors "
                        "BEGIN SELECT RAISE(ABORT, 'disk write failed'); END")
        self.db.commit()
        relay = runtime.Relay(self.config, self.db,
                              lambda req: {"ok": True, "sourceReadOk": True, "health": "online", "cursor": {"next": "new"},
                                           "messages": [self.event("uncommitted")]},
                              lambda *args: {"ok": True})
        with self.assertRaises(sqlite3.IntegrityError):
            relay.scan_profile("primary")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)
        self.assertEqual(json_cursor(self.db), old)

    def test_poison_event_and_external_id_body_conflict_freeze_cursor(self):
        old = runtime.compact({"next": "old"})
        self.db.execute("INSERT INTO cursors(connector_id,profile,value) VALUES('connector-a','primary',?)", (old,))
        original = runtime.compact(self.event("stable"))
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) "
                        "VALUES('connector-a','primary','stable',?,10)", (original,))
        self.db.commit()
        invalid = dict(self.event("poison"), senderName=None)
        relay = runtime.Relay(self.config, self.db,
                              lambda req: {"ok": True, "sourceReadOk": True, "health": "online", "cursor": {"next": "bad"},
                                           "messages": [invalid]}, lambda *args: {"ok": True})
        with self.assertRaisesRegex(RuntimeError, "invalid_event"):
            relay.scan_profile("primary")
        conflict = dict(self.event("stable"), body="different")
        relay.adapter_call = lambda req: {"ok": True, "sourceReadOk": True, "health": "online", "cursor": {"next": "bad"},
                                          "messages": [conflict]}
        with self.assertRaisesRegex(RuntimeError, "event_id_conflict_in_outbox"):
            relay.scan_profile("primary")
        self.assertEqual(json_cursor(self.db), old)

    def test_same_batch_external_id_conflict_keeps_rows_and_cursor_unchanged(self):
        old = runtime.compact({"next": "old"})
        self.db.execute("INSERT INTO cursors(connector_id,profile,value) VALUES('connector-a','primary',?)", (old,))
        self.db.commit()
        first = self.event("duplicate-id")
        second = dict(first, body="different")
        relay = runtime.Relay(self.config, self.db,
                              lambda _request: {"ok": True, "sourceReadOk": True, "health": "online", "cursor": {"next": "new"},
                                                "messages": [first, second]},
                              lambda *_args: {"ok": True})
        with self.assertRaisesRegex(RuntimeError, "event_id_conflict_in_page"):
            relay.scan_profile("primary")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)
        self.assertEqual(json_cursor(self.db), old)

    def test_same_batch_exact_duplicate_consumes_outbox_budget_once(self):
        message = dict(self.event("duplicate-id"), contentType="text")
        expected_size = len(runtime.compact({"connectorId": "connector-a", "messages": [message]}).encode())
        self.config["outboxMaxBytes"] = expected_size
        relay = runtime.Relay(self.config, self.db,
                              lambda _request: {"ok": True, "sourceReadOk": True, "health": "online", "cursor": {"next": "new"},
                                                "messages": [message, dict(message)]},
                              lambda *_args: {"ok": True})
        self.assertTrue(relay.scan_profile("primary"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox WHERE external_id='duplicate-id'").fetchone()[0], 1)
        self.assertEqual(relay.count_bytes("connector-a"), expected_size)
        self.assertEqual(json_cursor(self.db), runtime.compact({"next": "new"}))

    def test_page_that_would_exceed_capacity_does_not_advance_cursor(self):
        old = runtime.compact({"next": "old"})
        self.db.execute("INSERT INTO cursors(connector_id,profile,value) VALUES('connector-a','primary',?)", (old,))
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) "
                        "VALUES('connector-a','primary','existing','{}',10)")
        self.db.commit()
        self.config["outboxMaxBytes"] = 100
        relay = runtime.Relay(self.config, self.db,
                              lambda req: {"ok": True, "sourceReadOk": True, "health": "online", "cursor": {"next": "new"},
                                           "messages": [dict(self.event("next"), body="x" * 150)]},
                              lambda *args: {"ok": True})
        self.assertIsNone(relay.scan_profile("primary"))
        self.assertEqual(json_cursor(self.db), old)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)

    def test_scan_contract_supplies_page_and_byte_budgets(self):
        requests = []
        relay = runtime.Relay(self.config, self.db,
                              lambda request: requests.append(request) or {
                                  "ok": True, "sourceReadOk": True, "health": "online", "active": False,
                                  "cursor": {"next": 1}, "messages": [self.event("one")]},
                              lambda *args: {"ok": True})
        self.assertTrue(relay.scan_profile("primary"))
        self.assertEqual(requests[0]["limit"], 20)
        self.assertEqual(requests[0]["maxBytes"], runtime.MAX_SCAN_RESPONSE)
        self.assertEqual(requests[0]["maxEventBytes"], runtime.MAX_EVENT)

    def test_adapter_byte_pagination_advances_cursor_without_replaying_page(self):
        self.config["outboxMaxBytes"] = 3 * 1024 * 1024
        source = [dict(self.event("item-" + str(index)), body="x" * 200000) for index in range(8)]
        requests = []
        def adapter(request):
            requests.append(request)
            offset = request["cursor"] or 0
            page = []
            next_offset = offset
            for item in source[offset:]:
                candidate = page + [item]
                candidate_cursor = offset + len(candidate)
                envelope = {"ok": True, "sourceReadOk": True, "health": "online", "active": False,
                            "cursor": candidate_cursor, "messages": candidate}
                single = runtime.compact({"connectorId": "connector-a", "messages": [item]}).encode("utf-8")
                if (len(candidate) > request["limit"] or len(single) > request["maxEventBytes"] or
                        len(runtime.compact(envelope).encode("utf-8")) > request["maxBytes"]):
                    break
                page = candidate
                next_offset = candidate_cursor
            return {"ok": True, "sourceReadOk": True, "health": "online", "active": False,
                    "cursor": next_offset, "messages": page}
        relay = runtime.Relay(self.config, self.db, adapter, lambda *args: {"ok": True})
        relay.scan_profile("primary")
        first_cursor = json_cursor(self.db)
        self.assertEqual(int(first_cursor), 4)
        relay.scan_profile("primary")
        self.assertEqual(json_cursor(self.db), runtime.compact(8))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 8)
        self.assertLess(int(first_cursor), 8)
        self.assertEqual(requests[1]["cursor"], int(first_cursor))

    def test_oversized_scan_envelope_is_rejected_before_cursor_commit(self):
        old = runtime.compact({"next": "old"})
        self.db.execute("INSERT INTO cursors(connector_id,profile,value) VALUES('connector-a','primary',?)", (old,))
        self.db.commit()
        relay = runtime.Relay(self.config, self.db,
                              lambda request: {"ok": True, "sourceReadOk": True, "health": "online", "cursor": {"next": "new"},
                                  "messages": [], "padding": "x" * (runtime.MAX_SCAN_RESPONSE + 1)},
                              lambda *args: {"ok": True})
        with self.assertRaisesRegex(RuntimeError, "scan_response_too_large"):
            relay.scan_profile("primary")
        self.assertEqual(json_cursor(self.db), old)

    def test_scan_commits_cursor_atomically_with_durable_outbox(self):
        relay = runtime.Relay(self.config, self.db,
                              lambda req: {"ok": True, "sourceReadOk": True, "health": "online", "cursor": {"n": 3},
                                           "messages": [self.event("next")]},
                              lambda *args: {"ok": True})
        self.assertTrue(relay.scan_profile("primary"))
        self.assertEqual(json_cursor(self.db), runtime.compact({"n": 3}))
        self.assertEqual(self.db.execute("SELECT external_id FROM outbox").fetchone()[0], "next")

    def test_two_connector_identities_share_one_sequential_runtime(self):
        self.config["connectors"] = [
            {"id": "connector-a", "token": "a" * 40, "profile": "primary",
             "kind": "qq", "accountLabel": "A", "displayName": "A"},
            {"id": "connector-b", "token": "b" * 40, "profile": "primary",
             "kind": "wechat", "accountLabel": "B", "displayName": "B"},
        ]
        adapter_profiles = []
        requests = []
        def adapter(request):
            adapter_profiles.append(request["profile"])
            return {"ok": True, "sourceReadOk": True, "health": "online", "cursor": request["profile"],
                    "messages": [self.event(request["profile"])]}
        def http(method, path, payload=None):
            requests.append((method, path, payload))
            if path == "/api/connectors/events":
                return self.event_ack(len(payload["messages"]))
            return {"ok": True, "commands": []}
        relay = runtime.Relay(self.config, self.db, adapter, http)
        relay.pass_once()
        relay.pass_once()
        event_ids = [item[2]["connectorId"] for item in requests
                     if item[1].endswith("/events")]
        self.assertEqual(adapter_profiles, ["primary", "primary"])
        self.assertEqual(event_ids, ["connector-a", "connector-b"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM cursors WHERE profile='primary'").fetchone()[0], 2)

    def test_outbox_delivery_round_robins_after_large_connector_backlog(self):
        self.config["connectors"] = [
            {"id": "connector-a", "token": "a" * 40, "profile": "primary",
             "kind": "qq", "accountLabel": "A", "displayName": "A"},
            {"id": "connector-b", "token": "b" * 40, "profile": "primary",
             "kind": "wechat", "accountLabel": "B", "displayName": "B"},
        ]
        for index in range(12):
            message = self.event("a" + str(index))
            self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) "
                            "VALUES('connector-a','primary',?,?,1)",
                            ("a" + str(index), runtime.compact(message)))
        second_message = self.event("b0")
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) "
                        "VALUES('connector-b','primary','b0',?,1)", (runtime.compact(second_message),))
        self.db.commit()
        delivered = []
        relay = runtime.Relay(self.config, self.db, lambda request: {},
                              lambda method, path, payload=None: delivered.append(payload["connectorId"]) or
                                  self.event_ack(len(payload["messages"])))
        relay.flush_one()
        relay.flush_one()
        self.assertEqual(delivered, ["connector-a", "connector-b"])

    def test_failed_connector_does_not_block_another_outbox_delivery(self):
        self.config["connectors"] = [
            {"id": "connector-a", "token": "a" * 40, "profile": "primary",
             "kind": "qq", "accountLabel": "A", "displayName": "A"},
            {"id": "connector-b", "token": "b" * 40, "profile": "primary",
             "kind": "wechat", "accountLabel": "B", "displayName": "B"},
        ]
        first_message, second_message = self.event("a0"), self.event("b0")
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) "
                        "VALUES('connector-a','primary','a0',?,1)", (runtime.compact(first_message),))
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) "
                        "VALUES('connector-b','primary','b0',?,1)", (runtime.compact(second_message),))
        self.db.commit()
        delivered = []
        def http(method, path, payload=None):
            if payload["connectorId"] == "connector-a":
                raise OSError("connector A is offline")
            delivered.append(payload["connectorId"])
            return self.event_ack(len(payload["messages"]))
        relay = runtime.Relay(self.config, self.db, lambda request: {}, http)
        self.assertTrue(relay.flush_one())
        self.assertEqual(delivered, ["connector-b"])
        self.assertEqual(self.db.execute("SELECT connector_id FROM outbox").fetchone()[0], "connector-a")

    def test_background_group_text_uses_backup_route_and_other_events_use_ingest_route(self):
        group = dict(self.event("group-background"), conversationType="group")
        direct = self.event("direct-event")
        self_group = dict(self.event("self-group-background"), conversationType="group",
                          trigger="background", isSelf=True)
        system = dict(self.event("group-system-background"), conversationType="group",
                      trigger="background", isSelf=False, contentType="text", presentation="system")
        for message in (group, direct):
            self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,1)",
                            ("connector-a", "primary", message["externalId"], runtime.compact(message)))
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,1)",
                        ("connector-a", "primary", self_group["externalId"], runtime.compact(self_group)))
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,1)",
                        ("connector-a", "primary", system["externalId"], runtime.compact(system)))
        self.db.commit()
        calls = []
        uploaded = []
        relay = runtime.Relay(
            self.config, self.db, lambda request: {},
            lambda method, path, payload=None: calls.append((path, payload)) or
                (self.backup_ack(len(payload["messages"])) if path.endswith("group-text-backups") else
                 self.event_ack(len(payload["messages"]))))
        relay.upload_attachment = lambda message, attachment: uploaded.append(message["externalId"])
        self.assertTrue(relay.flush_one())
        self.assertTrue(relay.flush_one())
        self.assertEqual([path for path, _ in calls], [
            "/api/connectors/group-text-backups", "/api/connectors/events"])
        self.assertEqual([message["externalId"] for message in calls[1][1]["messages"]],
                         ["direct-event", "self-group-background", "group-system-background"])
        self.assertEqual(calls[1][1]["messages"][-1]["presentation"], "system")
        self.assertEqual(uploaded, [])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)

    def test_system_presentation_is_validated_before_normal_event_routing(self):
        base = dict(self.event("system-message"), conversationType="group", trigger="background",
                    isSelf=False, contentType="text", presentation="system")
        cases = [
            ("non-qq", {"connectorKind": "wechat"}),
            ("self", {"isSelf": True}),
            ("missing-direction", {"isSelf": None}),
            ("mixed-content", {"contentType": "mixed"}),
            ("blank-text", {"body": "  "}),
            ("bad-marker", {"presentation": "notice"}),
            ("null-marker", {"presentation": None}),
        ]
        for label, updates in cases:
            with self.subTest(label=label):
                connector = dict(self.config["connectors"][0])
                connector["kind"] = updates.get("connectorKind", "qq")
                self.config["connectors"] = [connector]
                message = {**base, **{key: value for key, value in updates.items() if key != "connectorKind"}}
                if message.get("isSelf") is None:
                    message.pop("isSelf")
                relay = runtime.Relay(self.config, self.db, lambda request: {
                    "ok": True, "sourceReadOk": True, "health": "online", "cursor": {}, "messages": [message],
                }, lambda *args: {"ok": True})
                with self.assertRaisesRegex(RuntimeError, "invalid_event_presentation"):
                    relay.scan_profile("primary")
        self.config["connectors"][0]["kind"] = "qq"
        message = {**base, "attachments": [{
            "externalId": "system-file", "stagingKey": "bad.png", "fileName": "bad.png",
            "mimeType": "image/png", "sizeBytes": 1, "sha256": "0" * 64,
        }]}
        relay = runtime.Relay(self.config, self.db, lambda request: {
            "ok": True, "sourceReadOk": True, "health": "online", "cursor": {}, "messages": [message],
        }, lambda *args: {"ok": True})
        with self.assertRaisesRegex(RuntimeError, "invalid_event_presentation"):
            relay.scan_profile("primary")

    def test_self_group_with_attachment_uses_normal_event_route_and_skips_backup_text_guard(self):
        media_root = os.path.join(self.temp.name, "media")
        media_dir = os.path.join(media_root, "connector-a")
        os.makedirs(media_dir)
        payload = b"self-group-image"
        with open(os.path.join(media_dir, "self-group-image.bin"), "wb") as staged:
            staged.write(payload)
        message = dict(self.event("self-group-media"), conversationType="group", trigger="background",
                       isSelf=True, body="", contentType="mixed", attachments=[{
                           "externalId": "file-self-group", "stagingKey": "self-group-image.bin",
                           "fileName": "photo.png", "mimeType": "image/png", "sizeBytes": len(payload),
                           "sha256": runtime.hashlib.sha256(payload).hexdigest(),
                       }])
        relay = runtime.Relay(self.config, self.db, lambda request: {
            "ok": True, "sourceReadOk": True, "health": "online", "cursor": {"next": "next"},
            "messages": [message],
        }, lambda *args: {"ok": True})
        relay.media_directory = media_root
        uploaded = []
        relay.upload_attachment = lambda event, attachment: uploaded.append(
            (event["externalId"], attachment["externalId"]))
        delivered = []
        relay.http_call = lambda method, path, payload=None: delivered.append((path, payload)) or self.event_ack(1)
        self.assertTrue(relay.scan_profile("primary"))
        self.assertTrue(relay.flush_one())
        self.assertEqual([path for path, _ in delivered], ["/api/connectors/events"])
        self.assertEqual(delivered[0][1]["messages"][0]["isSelf"], True)
        self.assertEqual(delivered[0][1]["messages"][0]["contentType"], "mixed")
        self.assertEqual(uploaded, [("self-group-media", "file-self-group")])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)

    def test_suppressed_ingest_response_keeps_outbox_and_backs_off(self):
        message = dict(self.event("group-mention"), conversationType="group", trigger="mention")
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,1)",
                        ("connector-a", "primary", message["externalId"], runtime.compact(message)))
        self.db.commit()
        relay = runtime.Relay(self.config, self.db, lambda request: {},
                              lambda *args: {"ok": True, "suppressed": 1})
        with patch.object(runtime.time, "monotonic", return_value=100):
            self.assertFalse(relay.flush_one())
            self.assertGreater(relay.outbox_retry_at["connector-a"], 100)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)
        group = dict(self.event("group-background"), conversationType="group", trigger="background")
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,1)",
                        ("connector-a", "primary", group["externalId"], runtime.compact(group)))
        self.db.commit()
        relay.outbox_retry_at["connector-a"] = 0
        with patch.object(runtime.time, "monotonic", return_value=200):
            self.assertFalse(relay.flush_one())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 2)

    def test_failed_outbox_delivery_does_not_block_bounded_source_scan(self):
        queued = dict(self.event("conflict-head"), conversationType="group", trigger="background")
        self.db.execute(
            "INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,1)",
            ("connector-a", "primary", queued["externalId"], runtime.compact(queued)),
        )
        self.db.commit()
        scanned = []
        incoming = self.event("new-source-event")

        def adapter(request):
            scanned.append(request)
            return {"ok": True, "sourceReadOk": True, "health": "online",
                    "cursor": {"next": "advanced"}, "messages": [incoming]}

        def http(method, path, payload=None):
            if path.endswith("group-text-backups"):
                raise RuntimeError("message_external_id_conflict")
            return {"ok": True, "commands": []}

        relay = runtime.Relay(self.config, self.db, adapter, http)
        with patch.object(runtime.time, "monotonic", return_value=1000):
            relay.pass_once()

        self.assertEqual(len(scanned), 1)
        self.assertEqual(json_cursor(self.db), runtime.compact({"next": "advanced"}))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 2)
        self.assertEqual(self.db.execute(
            "SELECT external_id FROM outbox ORDER BY seq LIMIT 1").fetchone()[0], "conflict-head")
        self.assertGreater(relay.outbox_retry_at["connector-a"], 1000)
        self.assertEqual(relay.retry_at["connector-a"], 0)
        self.assertTrue(relay.health["connector-a"])

    def test_failed_outbox_delivery_does_not_block_ready_auto_wake_scan(self):
        queued = dict(self.event("conflict-head"), conversationType="group", trigger="background")
        self.db.execute(
            "INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,1)",
            ("connector-a", "primary", queued["externalId"], runtime.compact(queued)),
        )
        self.db.commit()
        adapter_calls = []
        incoming = self.event("new-auto-wake-event")

        def adapter(request):
            adapter_calls.append(request)
            if request["op"] == "ensure-active":
                return self.wake_result(True)
            return {"ok": True, "sourceReadOk": True, "health": "online",
                    "cursor": {"next": "advanced"}, "messages": [incoming]}

        def http(method, path, payload=None):
            if path.endswith("group-text-backups"):
                raise RuntimeError("message_external_id_conflict")
            return {"ok": True, "commands": []}

        config = self.auto_wake_config()
        config["connectors"] = config["connectors"][:1]
        relay = runtime.Relay(config, self.db, adapter, http)
        relay.wake_readiness_established = True
        relay.source_settle_until["connector-a"] = 0
        with patch.object(runtime.time, "monotonic", return_value=1000):
            relay.pass_once()

        self.assertTrue(any(request["op"] == "scan" for request in adapter_calls))
        self.assertEqual(json_cursor(self.db), runtime.compact({"next": "advanced"}))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 2)
        self.assertGreater(relay.outbox_retry_at["connector-a"], 1000)
        self.assertTrue(relay.health["connector-a"])

    def test_source_read_failure_after_outbox_failure_keeps_scan_backoff(self):
        queued = dict(self.event("conflict-head"), conversationType="group", trigger="background")
        self.db.execute(
            "INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,1)",
            ("connector-a", "primary", queued["externalId"], runtime.compact(queued)),
        )
        self.db.commit()
        scans = []

        def adapter(request):
            if request["op"] == "scan":
                scans.append(request)
                return {"ok": False, "sourceReadOk": False, "nativeFailure": {"code": "unavailable"}}
            return {}

        def http(method, path, payload=None):
            if path.endswith("group-text-backups"):
                raise RuntimeError("message_external_id_conflict")
            return {"ok": True, "commands": []}

        relay = runtime.Relay(self.config, self.db, adapter, http)
        old_cursor = runtime.compact({"next": "old"})
        self.db.execute(
            "INSERT INTO cursors(connector_id,profile,value) VALUES('connector-a','primary',?)", (old_cursor,))
        self.db.commit()
        now = [1000.0]
        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]):
            relay.pass_once()
            self.assertEqual(len(scans), 1)
            self.assertGreater(relay.outbox_retry_at["connector-a"], now[0])
            self.assertGreater(relay.retry_at["connector-a"], now[0])
            now[0] += 1
            relay.pass_once()

        self.assertEqual(len(scans), 1)
        self.assertEqual(json_cursor(self.db), old_cursor)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)

    def test_normal_ingest_ack_with_zero_suppressed_is_deduplicated_before_delete(self):
        message = self.event("once")
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,1)",
                        ("connector-a", "primary", message["externalId"], runtime.compact(message)))
        self.db.commit()
        calls = []
        relay = runtime.Relay(self.config, self.db, lambda request: {},
                              lambda method, path, payload=None: calls.append(path) or
                                  self.event_ack(1, inserted=0, upgraded=1, promoted=1))
        self.assertTrue(relay.flush_one())
        self.assertFalse(relay.flush_one())
        self.assertEqual(calls, ["/api/connectors/events"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)

    def test_group_background_invalid_text_or_attachments_do_not_commit_cursor(self):
        old = runtime.compact({"next": "old"})
        self.db.execute("INSERT INTO cursors(connector_id,profile,value) VALUES('connector-a','primary',?)", (old,))
        self.db.commit()
        cases = [
            ("empty", "", None),
            ("too-long", "x" * 20001, None),
            ("utf16-too-long", "😀" * 10001, None),
            ("attachment", "text", [{"externalId": "file-1"}]),
        ]
        relay = runtime.Relay(self.config, self.db, lambda request: {}, lambda *args: {"ok": True})
        for external_id, body, attachments in cases:
            event = dict(self.event(external_id), conversationType="group", trigger="background", body=body)
            if attachments is not None:
                event["attachments"] = attachments
            relay.adapter_call = lambda request, item=event: {
                "ok": True, "sourceReadOk": True, "health": "online", "cursor": {"next": "new"}, "messages": [item]}
            expected = "invalid_staging_key" if attachments else "invalid_group_text_backup"
            with self.assertRaisesRegex(RuntimeError, expected):
                relay.scan_profile("primary")
            self.assertEqual(json_cursor(self.db), old)
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)

    def test_receive_only_connector_registers_without_send_and_never_polls_commands(self):
        self.config["connectors"][0]["receiveOnly"] = True
        calls = []
        relay = runtime.Relay(
            self.config, self.db,
            lambda request: {"ok": True, "sourceReadOk": True, "health": "online", "active": False,
                             "cursor": None, "messages": []},
            lambda method, path, payload=None: calls.append((method, path, payload)) or
                ({"ok": True, "commands": []} if path.endswith("/commands") else {"ok": True}))
        relay.register_connectors()
        relay.pass_once()
        registration = next(payload for _, path, payload in calls if path.endswith("/register"))
        self.assertEqual(registration["capabilities"], ["receive_text", "receive_images"])
        self.assertFalse(any(path.startswith("/api/connectors/commands") for _, path, _ in calls))

    def test_started_send_is_marked_uncertain_without_second_adapter_call(self):
        self.save_cursor()
        command = {"id": "command-1", "leaseToken": "lease-1", "idempotencyKey": "key-1",
                   "payload": {"externalConversationId": "conversation-aaaaaaaa", "body": "hello"}}
        adapter_calls = []
        completions = []
        def adapter(request):
            adapter_calls.append(request)
            raise TimeoutError("native result unavailable")
        relay = runtime.Relay(self.config, self.db, adapter,
                              lambda method, path, payload=None: completions.append(payload) or {"ok": True})
        relay.process_command(command, "primary")
        self.db.close()
        self.db = runtime.open_database(self.db_path)
        restarted = runtime.Relay(self.config, self.db,
                                  lambda request: adapter_calls.append(request),
                                  lambda method, path, payload=None: completions.append(payload) or {"ok": True})
        restarted.process_command(command, "primary")
        self.assertEqual(len(adapter_calls), 1)
        self.assertTrue(completions[-1]["uncertain"])

    def test_lost_completion_response_replays_saved_result_without_resending(self):
        self.save_cursor()
        command = {"id": "command-2", "leaseToken": "lease-2", "idempotencyKey": "key-2",
                   "payload": {"externalConversationId": "conversation-aaaaaaaa", "body": "hello"}}
        adapter_calls = []
        completion_calls = []
        def adapter(request):
            adapter_calls.append(request)
            return qq_receipt_result()
        def http(method, path, payload=None):
            if path.endswith("/complete"):
                completion_calls.append(payload)
            if path.endswith("/complete") and len(completion_calls) == 1:
                raise OSError("completion response lost")
            return {"ok": True}
        relay = runtime.Relay(self.config, self.db, adapter, http)
        with self.assertRaises(OSError):
            relay.process_command(command, "primary")
        self.db.execute("DELETE FROM cursors WHERE connector_id='connector-a' AND profile='primary'")
        self.db.commit()
        with patch.object(relay, "qq_send_cursor", side_effect=AssertionError("done command reloaded cursor")):
            relay.process_command(command, "primary")
        self.assertEqual(len(adapter_calls), 1)
        self.assertEqual(completion_calls[0], completion_calls[1])

    def test_invalid_lease_is_checked_before_native_send(self):
        command = {"id": "command-3", "leaseToken": "expired", "idempotencyKey": "key-3",
                   "payload": {"externalConversationId": "conversation-aaaaaaaa", "body": "hello"}}
        adapter_calls = []
        def http(method, path, payload=None):
            if path.endswith("/lease"):
                raise RuntimeError("invalid_command_lease")
            return {"ok": True}
        relay = runtime.Relay(self.config, self.db,
                              lambda request: adapter_calls.append(request), http)
        relay.process_command(command, "primary")
        self.assertEqual(adapter_calls, [])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM command_ledger").fetchone()[0], 0)

    def test_qq_send_cursor_requires_exact_connector_profile_and_valid_bounded_state(self):
        cases = (
            ("wrong-profile", "secondary", {"scope": "profile"}, "qq_send_scope_mismatch"),
            ("missing", "primary", None, "qq_send_cursor_unavailable"),
            ("invalid-json", "primary", "{", "qq_send_cursor_invalid"),
            ("invalid-shape", "primary", {"version": 2, "conversations": {}}, "qq_send_cursor_invalid"),
            ("oversized", "primary", {"version": 1, "conversations": {}, "x": "a" * 65540},
             "qq_send_cursor_oversized"),
        )
        for index, (label, profile, stored, expected_error) in enumerate(cases):
            with self.subTest(label=label):
                self.db.execute("DELETE FROM cursors")
                if isinstance(stored, str):
                    self.db.execute(
                        "INSERT INTO cursors(connector_id,profile,value) VALUES(?,?,?)",
                        ("connector-a", "primary", stored),
                    )
                    self.db.commit()
                elif stored is not None:
                    self.save_cursor(cursor=stored)
                adapter_calls = []
                completions = []
                relay = runtime.Relay(
                    self.config, self.db,
                    lambda request: adapter_calls.append(request) or qq_receipt_result(),
                    lambda method, path, payload=None: completions.append(payload) or {"ok": True},
                )
                command = {"id": f"cursor-{index}", "leaseToken": "lease-cursor",
                           "idempotencyKey": f"cursor-key-{index}",
                           "payload": {"externalConversationId": "conversation-aaaaaaaa",
                                       "body": "hello"}}
                relay.process_command(command, profile)
                self.assertEqual(adapter_calls, [])
                self.assertEqual(completions[-1]["connectorId"], "connector-a")
                self.assertEqual(completions[-1]["leaseToken"], "lease-cursor")
                self.assertEqual({key: completions[-1][key] for key in ("ok", "dispatched", "error")}, {
                    "ok": False, "dispatched": False, "error": expected_error,
                })
                state, result, retryable = self.db.execute(
                    "SELECT state,result,retryable FROM command_ledger WHERE connector_id=? AND idempotency_key=?",
                    ("connector-a", f"cursor-key-{index}"),
                ).fetchone()
                self.assertEqual(state, "done")
                self.assertEqual(json.loads(result), {
                    "ok": False, "dispatched": False, "error": expected_error,
                })
                self.assertEqual(retryable, 0)

    def test_qq_send_cursor_accepts_exact_existing_size_limit(self):
        base = {"version": 1, "conversations": {}}
        overhead = len(runtime.compact(dict(base, padding="")).encode("utf-8"))
        cursor = dict(base, padding="x" * (runtime.MAX_CURSOR_BYTES - overhead))
        self.assertEqual(len(runtime.compact(cursor).encode("utf-8")), runtime.MAX_CURSOR_BYTES)
        self.save_cursor(cursor=cursor)
        relay = runtime.Relay(self.config, self.db, lambda _request: {}, lambda *_args: {"ok": True})
        self.assertEqual(relay.qq_send_cursor(self.config["connectors"][0], "primary"), cursor)

    def test_qq_send_cursor_never_reads_another_connector_row(self):
        self.config["connectors"].append({
            "id": "connector-b", "token": "y" * 40, "kind": "qq",
            "accountLabel": "other", "displayName": "other", "profile": "primary",
        })
        self.db.execute(
            "INSERT INTO cursors(connector_id,profile,value) VALUES(?,?,?)",
            ("connector-b", "primary", runtime.compact({"version": 1, "conversations": {}})),
        )
        self.db.commit()
        relay = runtime.Relay(self.config, self.db, lambda _request: {}, lambda *_args: {"ok": True})
        with self.assertRaisesRegex(runtime.SendPreDispatchError, "qq_send_scope_mismatch"):
            relay.qq_send_cursor({"id": "connector-b", "kind": "qq", "profile": "primary"}, "primary")
        with self.assertRaisesRegex(runtime.SendPreDispatchError, "qq_send_cursor_unavailable"):
            relay.qq_send_cursor(self.config["connectors"][0], "primary")

    def test_wechat_send_request_does_not_receive_qq_cursor(self):
        wechat = {"id": "connector-b", "token": "y" * 40, "kind": "wechat",
                  "accountLabel": "other", "displayName": "other", "profile": "secondary"}
        self.config["connectors"].append(wechat)
        self.save_cursor(connector_id="connector-a", profile="primary")
        self.save_cursor(connector_id="connector-b", profile="secondary")
        adapter_calls = []
        completions = []
        relay = runtime.Relay(
            self.config, self.db,
            lambda request: adapter_calls.append(request) or {
                "ok": True, "receipt": "wechat-receipt", "dispatched": True,
            },
            lambda method, path, payload=None: completions.append(payload) or {"ok": True},
        )
        relay.select_connector(wechat)
        command = {"id": "wechat-command", "leaseToken": "lease-wechat", "idempotencyKey": "wechat-key",
                   "payload": {"externalConversationId": "conversation-aaaaaaaa", "body": "hello"}}
        relay.process_command(command, "secondary")
        self.assertEqual(len(adapter_calls), 1)
        self.assertEqual(adapter_calls[0]["driver"], "wechat")
        self.assertNotIn("cursor", adapter_calls[0])
        self.assertNotIn("cursor", completions[-1])
        wechat_cursor = json.loads(self.db.execute(
            "SELECT value FROM cursors WHERE connector_id='connector-b' AND profile='secondary'"
        ).fetchone()[0])
        self.assertNotIn("qqConfirmedSendReads", wechat_cursor)

    def test_leased_command_passes_driver_canonical_target_and_authorization(self):
        cursor = self.save_cursor()
        command = {
            "id": "command-authorized", "leaseToken": "lease-authorized",
            "idempotencyKey": "key-authorized",
            "payload": {"externalConversationId": "conversation-aaaaaaaa",
                        "body": "exact command body"},
        }
        adapter_calls = []
        http_calls = []
        timeline = []

        def adapter(request):
            timeline.append("adapter")
            ledger = self.db.execute(
                "SELECT state FROM command_ledger WHERE connector_id=? AND idempotency_key=?",
                ("connector-a", "key-authorized"),
            ).fetchone()
            self.assertEqual(ledger[0], "started")
            adapter_calls.append(request)
            return qq_receipt_result()

        def http(method, path, payload=None):
            http_calls.append((method, path, payload))
            if path.endswith("/lease"):
                timeline.append("lease")
            return {"ok": True}

        relay = runtime.Relay(
            self.config, self.db, adapter, http,
        )
        relay.process_command(command, "primary")
        self.assertEqual(len(adapter_calls), 1)
        request = adapter_calls[0]
        self.assertEqual(request["driver"], "qq")
        self.assertEqual(request["profile"], "primary")
        self.assertEqual(request["conversationExternalId"], "conversation-aaaaaaaa")
        self.assertEqual(request["body"], "exact command body")
        self.assertIs(request["confirmed"], True)
        self.assertIs(request["targetConfirmed"], True)
        self.assertEqual(request["cursor"], cursor)
        self.assertNotIn("targetAlias", request)
        self.assertNotIn("cursor", http_calls[-1][2])
        self.assertEqual(len(http_calls), 2)
        self.assertEqual(timeline, ["lease", "adapter"])

    def test_qq_receipt_external_id_is_forwarded_to_completion(self):
        self.save_cursor()
        command = {"id": "command-receipt-id", "leaseToken": "lease-receipt-id",
                   "idempotencyKey": "key-receipt-id",
                   "payload": {"externalConversationId": "conversation-aaaaaaaa", "body": "body"}}
        completions = []
        relay = runtime.Relay(self.config, self.db, lambda _: qq_receipt_result(),
                              lambda method, path, payload=None: completions.append(payload) or {"ok": True})
        relay.process_command(command, "primary")
        completion = next(payload for payload in completions if payload and "result" in payload)
        self.assertEqual(completion["result"]["externalId"], "primary:qq-message:9007199254740993")
        self.assertEqual(json.loads(completion["result"]["receipt"])["sourceId"], "9007199254740993")

    def test_verified_qq_send_registers_priority_read_with_latest_cursor_atomically(self):
        cursor = self.save_cursor()
        trace = []
        self.db.set_trace_callback(trace.append)
        adapter_calls = []
        adapter_requests = []

        def adapter(_request):
            adapter_calls.append(True)
            adapter_requests.append(_request)
            latest = dict(cursor, conversations={"conversation-aaaaaaaa": {"head": "new-head"}},
                          next={"page": 17}, sweep={"active": False})
            self.db.execute(
                "UPDATE cursors SET value=? WHERE connector_id=? AND profile=?",
                (runtime.compact(latest), "connector-a", "primary"),
            )
            self.db.commit()
            return qq_receipt_result()

        relay = runtime.Relay(
            self.config, self.db, adapter,
            lambda *_args: {"ok": True},
        )
        command = {
            "id": "priority-command", "leaseToken": "priority-lease",
            "idempotencyKey": "priority-key",
            "payload": {"externalConversationId": "conversation-aaaaaaaa", "body": "sent"},
        }
        relay.process_command(command, "primary")

        stored = json.loads(self.db.execute(
            "SELECT value FROM cursors WHERE connector_id='connector-a' AND profile='primary'"
        ).fetchone()[0])
        self.assertEqual(stored["conversations"], {"conversation-aaaaaaaa": {"head": "new-head"}})
        self.assertEqual(stored["next"], {"page": 17})
        self.assertEqual(stored["sweep"], {"active": False})
        self.assertEqual(stored["qqConfirmedSendReads"], [{
            "ownerUin": "1234", "alias": "conversation-aaaaaaaa",
            "sourceId": "9007199254740993", "remainingAttempts": 3,
        }])
        ledger = self.db.execute(
            "SELECT state,result FROM command_ledger WHERE connector_id='connector-a' AND idempotency_key='priority-key'"
        ).fetchone()
        self.assertEqual(ledger[0], "done")
        self.assertTrue(json.loads(ledger[1])["ok"])
        self.assertEqual(adapter_calls, [True])
        self.assertEqual(adapter_requests[0]["conversationExternalId"], "conversation-aaaaaaaa")
        transaction = trace[trace.index("BEGIN IMMEDIATE", max(
            index for index, statement in enumerate(trace) if statement == "BEGIN IMMEDIATE")):]
        completed = next(i for i, statement in enumerate(transaction)
                         if statement.startswith("UPDATE command_ledger SET state='done'"))
        cursor_update = next(i for i, statement in enumerate(transaction)
                             if statement.startswith("UPDATE cursors SET value="))
        commit = transaction.index("COMMIT")
        self.assertLess(completed, cursor_update)
        self.assertLess(cursor_update, commit)

    def test_priority_read_requires_verified_qq_and_matching_owner(self):
        cases = (
            ("bad-receipt", {"owner": "1234", "qdc_owner": None}, "reject"),
            ("missing-owner", {"owner": None, "qdc_owner": None}, "accept"),
            ("owner-conflict", {"owner": "1234", "qdc_owner": "5678"}, "accept"),
        )
        for index, (label, owners, receipt_mode) in enumerate(cases):
            with self.subTest(label=label):
                self.db.execute("DELETE FROM cursors")
                cursor = {"version": 1, "conversations": {"page": index}}
                if owners["owner"] is not None:
                    cursor["qqFriendDirectory"] = {
                        "version": "qfd1", "ownerUin": owners["owner"], "entries": [],
                        "lastAttemptUin": None, "lastAttemptAt": 0, "nextMainItem": 0,
                    }
                if owners["qdc_owner"] is not None:
                    cursor["qqDiscoveryCache"] = [
                        "qdc3", "primary", 42, False, 3600, 1, owners["qdc_owner"], [],
                    ]
                if label == "missing-owner":
                    cursor["qqConfirmedSendReads"] = {"malformed": True}
                self.save_cursor(cursor=cursor)
                result = qq_receipt_result()
                if receipt_mode == "reject":
                    result["externalId"] = "primary:qq-message:1"
                adapter_calls = []
                relay = runtime.Relay(
                    self.config, self.db,
                    lambda _request: adapter_calls.append(True) or result,
                    lambda *_args: {"ok": True},
                )
                command = {
                    "id": f"priority-negative-{index}", "leaseToken": "lease",
                    "idempotencyKey": f"priority-negative-key-{index}",
                    "payload": {"externalConversationId": "conversation-aaaaaaaa", "body": "sent"},
                }
                relay.process_command(command, "primary")
                stored = json.loads(self.db.execute(
                    "SELECT value FROM cursors WHERE connector_id='connector-a' AND profile='primary'"
                ).fetchone()[0])
                self.assertNotIn("qqConfirmedSendReads", stored)
                if receipt_mode == "reject":
                    self.assertEqual(stored["conversations"], {"page": index})
                    self.assertTrue(json.loads(self.db.execute(
                        "SELECT result FROM command_ledger WHERE idempotency_key=?",
                        (f"priority-negative-key-{index}",),
                    ).fetchone()[0])["uncertain"])
                else:
                    self.assertTrue(json.loads(self.db.execute(
                        "SELECT result FROM command_ledger WHERE idempotency_key=?",
                        (f"priority-negative-key-{index}",),
                    ).fetchone()[0])["ok"])
                self.assertEqual(adapter_calls, [True])

    def test_priority_read_uses_profile_scoped_qdc3_and_updates_only_active_connector(self):
        self.config["connectors"].append({
            "id": "connector-b", "token": "y" * 40, "kind": "qq",
            "accountLabel": "other", "displayName": "other", "profile": "secondary",
        })
        first = self.save_cursor(cursor={"version": 1, "conversations": {"keep": "a"}})
        second = {
            "version": 1, "conversations": {"keep": "b"},
            "qqDiscoveryCache": [
                "qdc3", "secondary", 42, False, 3600, 1, "987654321", [],
            ],
        }
        self.save_cursor(connector_id="connector-b", profile="secondary", cursor=second)
        result = qq_receipt_result()
        result["externalId"] = "secondary:qq-message:9007199254740993"
        relay = runtime.Relay(self.config, self.db,
                              lambda _request: result, lambda *_args: {"ok": True})
        relay.select_connector(self.config["connectors"][1])
        command = {
            "id": "priority-scope", "leaseToken": "lease", "idempotencyKey": "priority-scope-key",
            "payload": {"externalConversationId": "conversation-bbbbbbbb", "body": "sent"},
        }
        relay.process_command(command, "secondary")
        primary_after = json.loads(self.db.execute(
            "SELECT value FROM cursors WHERE connector_id='connector-a' AND profile='primary'"
        ).fetchone()[0])
        secondary_after = json.loads(self.db.execute(
            "SELECT value FROM cursors WHERE connector_id='connector-b' AND profile='secondary'"
        ).fetchone()[0])
        self.assertEqual(primary_after, first)
        self.assertEqual(secondary_after["conversations"], {"keep": "b"})
        self.assertEqual(secondary_after["qqConfirmedSendReads"], [{
            "ownerUin": "987654321", "alias": "conversation-bbbbbbbb",
            "sourceId": "9007199254740993", "remainingAttempts": 3,
        }])

    def test_priority_read_drops_malformed_queue_and_keeps_latest_target_once(self):
        cursor = self.save_cursor()
        cursor["qqConfirmedSendReads"] = [{"ownerUin": "1234", "alias": "bad"}]
        cursor["scanAnchor"] = {"before": "keep"}
        self.save_cursor(cursor=cursor)
        command = {
            "id": "priority-malformed", "leaseToken": "lease",
            "idempotencyKey": "priority-malformed-key",
            "payload": {"externalConversationId": "conversation-aaaaaaaa", "body": "sent"},
        }
        calls = []
        relay = runtime.Relay(
            self.config, self.db,
            lambda _request: calls.append(True) or qq_receipt_result(),
            lambda *_args: {"ok": True},
        )
        relay.process_command(command, "primary")
        updated = json.loads(self.db.execute(
            "SELECT value FROM cursors WHERE connector_id='connector-a' AND profile='primary'"
        ).fetchone()[0])
        self.assertEqual(updated["scanAnchor"], {"before": "keep"})
        self.assertEqual(len(updated["qqConfirmedSendReads"]), 1)
        self.assertEqual(updated["qqConfirmedSendReads"][0]["sourceId"], "9007199254740993")
        relay.process_command(command, "primary")
        unchanged = json.loads(self.db.execute(
            "SELECT value FROM cursors WHERE connector_id='connector-a' AND profile='primary'"
        ).fetchone()[0])
        self.assertEqual(len(unchanged["qqConfirmedSendReads"]), 1)
        self.assertEqual(calls, [True])

    def test_priority_read_replaces_duplicate_in_place_and_evicts_oldest_at_capacity(self):
        cursor = self.save_cursor()
        cursor["qqConfirmedSendReads"] = [
            {"ownerUin": "1234", "alias": f"conversation-{index:08x}",
             "sourceId": str(index + 1), "remainingAttempts": 1}
            for index in range(runtime.MAX_QQ_CONFIRMED_SEND_READS)
        ]
        cursor["qqConfirmedSendReads"][3]["alias"] = "conversation-aaaaaaaa"
        self.save_cursor(cursor=cursor)
        command = {
            "id": "priority-capacity", "leaseToken": "lease",
            "idempotencyKey": "priority-capacity-key",
            "payload": {"externalConversationId": "conversation-aaaaaaaa", "body": "sent"},
        }
        relay = runtime.Relay(self.config, self.db, lambda _request: qq_receipt_result(),
                              lambda *_args: {"ok": True})
        relay.process_command(command, "primary")
        queue = json.loads(self.db.execute(
            "SELECT value FROM cursors WHERE connector_id='connector-a' AND profile='primary'"
        ).fetchone()[0])["qqConfirmedSendReads"]
        self.assertEqual(len(queue), runtime.MAX_QQ_CONFIRMED_SEND_READS)
        self.assertEqual(queue[0]["alias"], "conversation-00000000")
        self.assertEqual(queue[2]["alias"], "conversation-00000002")
        self.assertEqual(queue[3]["alias"], "conversation-aaaaaaaa")
        self.assertEqual(queue[3]["sourceId"], "9007199254740993")
        self.assertEqual(queue[3]["remainingAttempts"], 3)
        other = {
            "id": "priority-capacity-second", "leaseToken": "lease",
            "idempotencyKey": "priority-capacity-key-second",
            "payload": {"externalConversationId": "conversation-bbbbbbbb", "body": "sent"},
        }
        relay.process_command(other, "primary")
        queue = json.loads(self.db.execute(
            "SELECT value FROM cursors WHERE connector_id='connector-a' AND profile='primary'"
        ).fetchone()[0])["qqConfirmedSendReads"]
        self.assertEqual(len(queue), runtime.MAX_QQ_CONFIRMED_SEND_READS)
        self.assertEqual(queue[0]["alias"], "conversation-00000001")
        self.assertEqual(queue[-1]["alias"], "conversation-bbbbbbbb")

    def test_priority_read_respects_cursor_byte_limit_without_changing_send_result(self):
        base = {"version": 1, "conversations": {},
                "qqFriendDirectory": {
                    "version": "qfd1", "ownerUin": "1234", "entries": [],
                    "lastAttemptUin": None, "lastAttemptAt": 0, "nextMainItem": 0,
                }}
        overhead = len(runtime.compact(dict(base, padding="")).encode("utf-8"))
        cursor = dict(base, padding="x" * (runtime.MAX_CURSOR_BYTES - overhead - 4))
        self.assertLessEqual(len(runtime.compact(cursor).encode("utf-8")), runtime.MAX_CURSOR_BYTES)
        self.save_cursor(cursor=cursor)
        command = {
            "id": "priority-size", "leaseToken": "lease", "idempotencyKey": "priority-size-key",
            "payload": {"externalConversationId": "conversation-aaaaaaaa", "body": "sent"},
        }
        relay = runtime.Relay(self.config, self.db, lambda _request: qq_receipt_result(),
                              lambda *_args: {"ok": True})
        relay.process_command(command, "primary")
        stored = self.db.execute(
            "SELECT value FROM cursors WHERE connector_id='connector-a' AND profile='primary'"
        ).fetchone()[0]
        self.assertEqual(stored, runtime.compact(cursor))
        ledger = self.db.execute(
            "SELECT state,result FROM command_ledger WHERE idempotency_key='priority-size-key'"
        ).fetchone()
        self.assertEqual(ledger[0], "done")
        self.assertTrue(json.loads(ledger[1])["ok"])

    def test_priority_cursor_write_failure_does_not_undo_confirmed_send(self):
        cursor = self.save_cursor()
        old_value = runtime.compact(cursor)
        self.db.execute(
            "CREATE TRIGGER reject_priority_cursor BEFORE UPDATE OF value ON cursors "
            "WHEN instr(NEW.value,'qqConfirmedSendReads')>0 "
            "BEGIN SELECT RAISE(ABORT,'priority metadata unavailable'); END"
        )
        self.db.commit()
        command = {
            "id": "priority-write-failure", "leaseToken": "lease",
            "idempotencyKey": "priority-write-failure-key",
            "payload": {"externalConversationId": "conversation-aaaaaaaa", "body": "sent"},
        }
        relay = runtime.Relay(self.config, self.db, lambda _request: qq_receipt_result(),
                              lambda *_args: {"ok": True})
        relay.process_command(command, "primary")
        stored = self.db.execute(
            "SELECT value FROM cursors WHERE connector_id='connector-a' AND profile='primary'"
        ).fetchone()[0]
        ledger = self.db.execute(
            "SELECT state,result FROM command_ledger WHERE idempotency_key='priority-write-failure-key'"
        ).fetchone()
        self.assertEqual(stored, old_value)
        self.assertEqual(ledger[0], "done")
        self.assertTrue(json.loads(ledger[1])["ok"])

    def test_qq_receipt_mismatch_is_terminal_uncertain(self):
        self.save_cursor()
        command = {"id": "command-bad-receipt", "leaseToken": "lease-bad-receipt",
                   "idempotencyKey": "key-bad-receipt",
                   "payload": {"externalConversationId": "conversation-aaaaaaaa", "body": "body"}}
        adapter_calls = []
        completions = []
        result = qq_receipt_result()
        result["externalId"] = "primary:message-00000000"
        relay = runtime.Relay(self.config, self.db,
                              lambda request: adapter_calls.append(request) or result,
                              lambda method, path, payload=None: completions.append(payload) or {"ok": True})
        relay.process_command(command, "primary")
        relay.process_command(command, "primary")
        self.assertEqual(len(adapter_calls), 1)
        self.assertTrue(completions[-1]["uncertain"])
        self.assertEqual(completions[-1]["error"], "qq_receipt_identity_unverified")

    def test_retryable_unknown_dispatch_is_uncertain_and_never_retried(self):
        self.save_cursor()
        command = {"id": "command-4", "leaseToken": "lease-4", "idempotencyKey": "key-4",
                   "payload": {"externalConversationId": "conversation-aaaaaaaa", "body": "hello"}}
        adapter_calls = []
        completions = []
        def adapter(request):
            adapter_calls.append(request)
            return {"ok": False, "retryable": True, "error": "timeout"}
        relay = runtime.Relay(self.config, self.db, adapter,
                              lambda method, path, payload=None: completions.append(payload) or {"ok": True})
        relay.process_command(command, "primary")
        relay.process_command(command, "primary")
        self.assertEqual(len(adapter_calls), 1)
        self.assertTrue(completions[-1]["uncertain"])

    def test_reused_idempotency_key_with_changed_payload_is_fenced(self):
        self.save_cursor()
        command = {"id": "command-5", "leaseToken": "lease-5", "idempotencyKey": "key-5",
                   "payload": {"externalConversationId": "conversation-aaaaaaaa", "body": "hello"}}
        adapter_calls = []
        completions = []
        relay = runtime.Relay(self.config, self.db,
                              lambda request: adapter_calls.append(request) or qq_receipt_result(),
                              lambda method, path, payload=None: completions.append(payload) or {"ok": True})
        relay.process_command(command, "primary")
        changed = dict(command, id="command-6", leaseToken="lease-6",
                       payload={"externalConversationId": "conversation-bbbbbbbb", "body": "different"})
        relay.process_command(changed, "primary")
        self.assertEqual(len(adapter_calls), 1)
        self.assertEqual(completions[-1]["error"], "device_idempotency_key_conflict")

    def test_adapter_paths_resolve_from_config_directory(self):
        value = runtime.resolve_local_paths({"database": "state/runtime.sqlite", "adapter": "private/adapter"},
                                            os.path.join(self.temp.name, "config.json"))
        self.assertEqual(os.path.normpath(value["database"]), os.path.join(self.temp.name, "state", "runtime.sqlite"))
        self.assertEqual(os.path.normpath(value["adapter"]), os.path.join(self.temp.name, "private", "adapter"))

    def test_adapter_retries_pipe_readiness_races_within_deadline(self):
        class Pipe:
            def __init__(self, fd):
                self.fd = fd
                self.closed = False

            def fileno(self):
                return self.fd

            def close(self):
                self.closed = True

        class Process:
            pid = 123

            def __init__(self):
                self.stdin = Pipe(101)
                self.stdout = Pipe(102)

            def wait(self, timeout=None):
                return 0

        class Selector:
            def __init__(self):
                self.keys = {}

            def register(self, fileobj, events, data):
                self.keys[fileobj] = type("Key", (), {"data": data})()

            def unregister(self, fileobj):
                del self.keys[fileobj]

            def select(self, timeout=None):
                return [(key, 0) for key in self.keys.values()]

            def close(self):
                pass

        process = Process()
        selectors = Selector()
        response = iter((b'{"ok":true}', b""))
        races = {"write": 0, "read": 0}

        def write(fd, data):
            if races["write"] == 0:
                races["write"] += 1
                raise BlockingIOError(11, "temporarily unavailable")
            return len(data)

        def read(fd, size):
            if races["read"] == 0:
                races["read"] += 1
                raise BlockingIOError(11, "temporarily unavailable")
            return next(response)

        with patch.object(runtime.subprocess, "Popen", return_value=process), \
                patch.object(runtime.os, "set_blocking", create=True), \
                patch.object(runtime.os, "write", side_effect=write), \
                patch.object(runtime.os, "read", side_effect=read), \
                patch.object(runtime.selectors, "DefaultSelector", return_value=selectors):
            result = runtime.run_adapter("adapter", {"op": "ensure-active"}, timeout=2)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(races, {"write": 1, "read": 1})
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)

    @unittest.skipUnless(os.name == "posix", "device process pipes use POSIX selectors")
    def test_adapter_deadline_bounds_large_input_oversized_output_and_closed_stdout(self):
        script = os.path.join(self.temp.name, "adapter")
        cases = [
            "import sys; sys.stdout.write('x' * 1100000)",
            "import sys,time; sys.stdout.close(); time.sleep(10)",
            "import time; time.sleep(10)",
        ]
        for index, body in enumerate(cases):
            with self.subTest(index=index):
                with open(script, "w", encoding="utf-8") as output:
                    output.write("#!/usr/bin/env python3\n" + body + "\n")
                os.chmod(script, 0o700)
                started = time.monotonic()
                with self.assertRaises(RuntimeError):
                    runtime.run_adapter(script, {"input": "x" * (4 * 1024 * 1024)}, timeout=0.25)
                self.assertLess(time.monotonic() - started, 3)
        for parent_mode in ("exits", "waits"):
            with self.subTest(parent_mode=parent_mode):
                marker = os.path.join(self.temp.name, "survived-" + parent_mode)
                child_ready = os.path.join(self.temp.name, "timeout-child-ready-" + parent_mode + ".json")
                parent_ready = os.path.join(self.temp.name, "timeout-parent-ready-" + parent_mode + ".json")
                release = os.path.join(self.temp.name, "timeout-child-release-" + parent_mode)
                child = (
                    "import json,os,time\n"
                    "with open(" + repr(child_ready) + ", 'w', encoding='utf-8') as f:\n"
                    " json.dump({'pid': os.getpid(), 'pgid': os.getpgrp()}, f)\n"
                    "deadline=time.monotonic()+30\n"
                    "while not os.path.exists(" + repr(release) + ") and time.monotonic()<deadline: time.sleep(.01)\n"
                    "if os.path.exists(" + repr(release) + "): open(" + repr(marker) + ", 'w').close()\n"
                )
                parent = (
                    "import json,os,subprocess,sys,time\n"
                    "subprocess.Popen([sys.executable, '-c', " + repr(child) + "], stderr=subprocess.DEVNULL)\n"
                    "deadline=time.monotonic()+10\n"
                    "while not os.path.exists(" + repr(child_ready) + ") and time.monotonic()<deadline: time.sleep(.01)\n"
                    "if not os.path.exists(" + repr(child_ready) + "): raise SystemExit(7)\n"
                    "with open(" + repr(parent_ready) + ", 'w', encoding='utf-8') as f:\n"
                    " json.dump({'pid': os.getpid(), 'pgid': os.getpgrp()}, f)\n"
                    "if " + repr(parent_mode) + " == 'waits': time.sleep(30)\n"
                )
                with open(script, "w", encoding="utf-8") as output:
                    output.write("#!/usr/bin/env python3\n" + parent)
                os.chmod(script, 0o700)
                child_pid = child_pgid = parent_pid = parent_pgid = None
                try:
                    with self.assertRaises(RuntimeError):
                        runtime.run_adapter(script, {"input": "x"}, timeout=2)
                    self.assertTrue(os.path.exists(child_ready), "child must be started before timeout")
                    with open(child_ready, encoding="utf-8") as source:
                        child_info = json.load(source)
                    child_pid, child_pgid = child_info["pid"], child_info["pgid"]
                    self.assertTrue(os.path.exists(parent_ready), "parent must observe child readiness")
                    with open(parent_ready, encoding="utf-8") as source:
                        parent_info = json.load(source)
                    parent_pid, parent_pgid = parent_info["pid"], parent_info["pgid"]
                    self.assertEqual(child_pgid, parent_pgid, "child must share the owned helper group")
                    self.assertEqual(parent_pgid, parent_pid, "helper must own its new session")
                    with open(release, "w", encoding="utf-8"):
                        pass
                    deadline = time.monotonic() + 0.5
                    while not os.path.exists(marker) and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertFalse(os.path.exists(marker), "timed-out process group must not retain a live child")
                finally:
                    if child_pid is None and os.path.exists(child_ready):
                        try:
                            with open(child_ready, encoding="utf-8") as source:
                                child_info = json.load(source)
                            child_pid, child_pgid = child_info["pid"], child_info["pgid"]
                        except (OSError, ValueError, KeyError):
                            pass
                    if parent_pid is None and os.path.exists(parent_ready):
                        try:
                            with open(parent_ready, encoding="utf-8") as source:
                                parent_info = json.load(source)
                            parent_pid, parent_pgid = parent_info["pid"], parent_info["pgid"]
                        except (OSError, ValueError, KeyError):
                            pass
                    for owned_pid, owned_pgid in ((child_pid, child_pgid), (parent_pid, parent_pgid)):
                        if owned_pid is not None:
                            try:
                                if os.getpgid(owned_pid) == owned_pgid:
                                    os.kill(owned_pid, signal.SIGKILL)
                            except OSError:
                                pass

    def test_adapter_invalid_json_kills_remaining_group_children(self):
        script = os.path.join(self.temp.name, "adapter")
        marker = os.path.join(self.temp.name, "survived-invalid-json")
        started = os.path.join(self.temp.name, "child-started")
        child = "open(" + repr(started) + ", 'w').close();import time;time.sleep(.8);open(" + repr(marker) + ", 'w').close()"
        compile(child, "<adapter-child>", "exec")
        script_text = ("#!/usr/bin/env python3\nimport os,subprocess,sys,time\n"
                       "subprocess.Popen([sys.executable, '-c', " + repr(child) + "], "
                       "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                       "while not os.path.exists(" + repr(started) + "): time.sleep(.01)\n"
                       "sys.stdout.close()\n")
        compile(script_text, script, "exec")
        if os.name != "posix":
            self.skipTest("adapter process groups are POSIX-only")
        with open(script, "w", encoding="utf-8") as output:
            output.write(script_text)
        os.chmod(script, 0o700)
        with self.assertRaises(json.JSONDecodeError):
            runtime.run_adapter(script, {"input": "x"}, timeout=2)
        time.sleep(1)
        self.assertFalse(os.path.exists(marker))

    def test_register_failure_does_not_starve_other_connector(self):
        self.config["connectors"] = [
            {"id": "connector-a", "token": "a" * 40, "profile": "primary",
             "kind": "qq", "accountLabel": "A", "displayName": "A"},
            {"id": "connector-b", "token": "b" * 40, "profile": "primary",
             "kind": "wechat", "accountLabel": "B", "displayName": "B"},
        ]
        attempted = []
        def http(method, path, payload=None):
            attempted.append(payload["id"])
            if payload["id"] == "connector-a":
                raise OSError("offline")
            return {"ok": True}
        relay = runtime.Relay(self.config, self.db, lambda req: {}, http)
        relay.register_connectors()
        self.assertEqual(attempted, ["connector-a", "connector-b"])
        self.assertEqual(relay.registered, {"connector-b"})

    def test_scan_failure_backs_off_only_failed_connector_and_retries_promptly(self):
        self.config["connectors"] = [
            {"id": "connector-a", "token": "a" * 40, "profile": "primary",
             "kind": "qq", "accountLabel": "A", "displayName": "A"},
            {"id": "connector-b", "token": "b" * 40, "profile": "primary",
             "kind": "wechat", "accountLabel": "B", "displayName": "B"},
        ]
        scanned = []
        now = [1000.0]
        relay = None
        def adapter(request):
            scanned.append(relay.connector)
            if relay.connector == "connector-a":
                raise OSError("adapter offline")
            return {"ok": True, "sourceReadOk": True, "health": "online", "cursor": None, "messages": []}
        relay = runtime.Relay(self.config, self.db, adapter, lambda *args: {"ok": True, "commands": []})
        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]):
            relay.pass_once()
            now[0] += 15
            relay.pass_once()
        self.assertEqual(scanned, ["connector-a", "connector-b", "connector-a"])
        self.assertTrue(relay.health["connector-b"])

    def test_control_loop_throttles_same_state_heartbeats_and_scans_on_idle_interval(self):
        calls = []
        scans = []
        now = [1000.0]
        def adapter(request):
            scans.append(request)
            return {"ok": True, "sourceReadOk": True, "health": "online", "active": False, "cursor": None, "messages": []}
        def http(method, path, payload=None):
            calls.append((method, path, payload))
            return {"ok": True, "commands": []}
        relay = runtime.Relay(self.config, self.db, adapter, http)
        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]):
            relay.pass_once()
            now[0] += 15
            relay.pass_once()
            now[0] += 285
            relay.pass_once()
        self.assertEqual(len(scans), 2)
        self.assertEqual(len([call for call in calls if call[1].endswith("/heartbeat")]), 2)

    def test_scan_failure_still_sends_offline_heartbeat_during_connector_backoff(self):
        heartbeat_payloads = []
        now = [1000.0]

        def adapter(_request):
            raise OSError("adapter unavailable")

        def http(method, path, payload=None):
            if path.endswith("/heartbeat"):
                heartbeat_payloads.append(payload)
            return {"ok": True, "commands": []}

        relay = runtime.Relay(self.config, self.db, adapter, http)
        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]):
            relay.pass_once()
            self.assertGreater(relay.retry_at["connector-a"], now[0])
            now[0] += 1
            relay.pass_once()

        self.assertEqual(len(heartbeat_payloads), 1)
        self.assertTrue(all(item["state"] == "offline" for item in heartbeat_payloads))

    def test_outbox_ack_keeps_heartbeat_online_without_opening_command_gate(self):
        for index in range(runtime.MAX_DELIVERIES_PER_PASS * runtime.MAX_OUTBOX_BATCH_MESSAGES + 1):
            message = self.event("queued-" + str(index))
            self.db.execute(
                "INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,1)",
                ("connector-a", "primary", "queued-" + str(index), runtime.compact(message)),
            )
        self.db.commit()
        calls = []

        def http(method, path, payload=None):
            calls.append((method, path, payload))
            if path == "/api/connectors/events":
                return self.event_ack(len(payload["messages"]))
            return {"ok": True, "commands": []}

        relay = runtime.Relay(self.config, self.db, lambda _request: {}, http)
        with patch.object(runtime.time, "monotonic", return_value=1000.0):
            relay.pass_once()

        heartbeat = next(payload for _method, path, payload in calls if path.endswith("/heartbeat"))
        self.assertEqual(heartbeat["state"], "online")
        self.assertFalse(relay.health["connector-a"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)
        self.assertFalse(any(method == "GET" and path.startswith("/api/connectors/commands")
                             for method, path, _payload in calls))

    def test_slow_outbox_acks_emit_throttled_progress_heartbeats(self):
        for ident in ("queued-a", "queued-b", "queued-c"):
            message = self.event(ident)
            self.db.execute(
                "INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,1)",
                ("connector-a", ident, ident, runtime.compact(message)),
            )
        self.db.commit()
        now = [100.0]
        calls = []

        def http(method, path, payload=None):
            calls.append((now[0], method, path, payload))
            if path.endswith("/events"):
                now[0] += 60
                return self.event_ack(len(payload["messages"]))
            return {"ok": True, "commands": []}

        relay = runtime.Relay(self.config, self.db,
                              lambda _request: {"ok": True, "sourceReadOk": False}, http)
        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]):
            relay.pass_once()

        heartbeat_rows = [row for row in calls if row[2].endswith("/heartbeat")]
        event_rows = [row for row in calls if row[2].endswith("/events")]
        self.assertEqual(len(event_rows), 3)
        self.assertEqual([row[3]["state"] for row in heartbeat_rows], ["online"] * 3)
        for index, event_row in enumerate(event_rows):
            following = [row for row in calls if row[0] >= event_row[0] + 60]
            self.assertTrue(following)
            self.assertTrue(following[0][2].endswith("/heartbeat"))
            self.assertEqual(following[0][3]["state"], "online")
        self.assertFalse(any(row[1] == "GET" and "/commands?" in row[2] for row in calls))

    def test_slow_profile_and_avatar_acks_keep_heartbeat_progress_bounded(self):
        now = [100.0]
        http_calls = []
        png = b"\x89PNG\r\n\x1a\nsmall-avatar"
        encoded_avatar = base64.b64encode(png).decode("ascii")
        profiles = [{"conversationExternalId": f"profile-{index}", "displayName": "Profile"}
                    for index in range(20)]
        avatars = [{"senderId": f"sender-{index}", "avatarBase64": encoded_avatar}
                   for index in range(20)]

        class SlowResponse:
            def __init__(self, url):
                self.url = url

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self):
                return self.url

            def read(self, _limit):
                return b'{"ok":true}'

        class SlowOpener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout):
                self.requests.append((request, timeout))
                now[0] += 5
                return SlowResponse(request.full_url)

        opener = SlowOpener()
        relay = runtime.Relay(self.config, self.db,
                              lambda _request: {"ok": True, "sourceReadOk": True,
                                                "health": "online", "cursor": {"next": "done"},
                                                "messages": [], "conversationProfiles": profiles,
                                                "senderAvatars": avatars},
                              lambda method, path, payload=None:
                                  http_calls.append((now[0], method, path, payload)) or {"ok": True})
        relay.select_connector(relay.connectors[0])

        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]), \
                patch.object(conversation_profiles.urllib.request, "build_opener", return_value=opener):
            self.assertTrue(relay.scan_profile("primary"))

        profile_requests = [request for request, _timeout in opener.requests
                            if "/conversation-profiles/" in request.full_url]
        avatar_requests = [request for request, _timeout in opener.requests
                           if "/sender-avatars/" in request.full_url]
        self.assertEqual(len(profile_requests), 20)
        self.assertEqual(len(avatar_requests), 20)
        heartbeat_rows = [row for row in http_calls if row[2].endswith("/heartbeat")]
        self.assertGreater(now[0] - 100, 90)
        self.assertGreaterEqual(len(heartbeat_rows), 6)
        self.assertTrue(all(row[3]["state"] == "online" for row in heartbeat_rows))
        self.assertTrue(all(right[0] - left[0] >= runtime.HEARTBEAT_MIN_INTERVAL
                            for left, right in zip(heartbeat_rows, heartbeat_rows[1:])))
        self.assertTrue(any(row[0] >= 200 for row in heartbeat_rows))
        self.assertEqual(relay.source_failures["connector-a"], 0)
        self.assertEqual(relay.failures["connector-a"], 0)

    def test_profile_ack_heartbeat_failure_does_not_fail_scan_or_connector_backoff(self):
        now = [100.0]

        def http(_method, path, _payload=None):
            if path.endswith("/heartbeat"):
                raise OSError("heartbeat offline")
            return {"ok": True}

        relay = runtime.Relay(
            self.config, self.db,
            lambda _request: {"ok": True, "sourceReadOk": True, "health": "online",
                              "cursor": {"next": "done"}, "messages": [],
                              "conversationProfiles": [{"conversationExternalId": "profile-a",
                                                         "displayName": "Profile"}]}, http)
        relay.select_connector(relay.connectors[0])

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self):
                return "https://worker.example/api/connectors/conversation-profiles/profile-a"

            def read(self, _limit):
                return b'{"ok":true}'

        class Opener:
            def open(self, _request, timeout):
                self.timeout = timeout
                return Response()

        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]), \
                patch.object(conversation_profiles.urllib.request, "build_opener", return_value=Opener()):
            self.assertTrue(relay.scan_profile("primary"))

        self.assertEqual(relay.heartbeat_failures["connector-a"], 1)
        self.assertEqual(relay.failures["connector-a"], 0)
        self.assertEqual(relay.source_failures["connector-a"], 0)
        self.assertEqual(json_cursor(self.db), runtime.compact({"next": "done"}))

    def test_same_state_heartbeat_is_throttled_but_state_change_is_immediate(self):
        now = [100.0]
        calls = []

        def http(method, path, payload=None):
            calls.append((now[0], payload["state"]))
            return {"ok": True}

        relay = runtime.Relay(self.config, self.db, http_call=http)
        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]):
            self.assertTrue(relay.send_heartbeat("connector-a", "online"))
            now[0] += 10
            self.assertFalse(relay.send_heartbeat("connector-a", "online"))
            self.assertTrue(relay.send_heartbeat("connector-a", "offline"))
            now[0] += 10
            self.assertFalse(relay.send_heartbeat("connector-a", "offline"))
            now[0] += runtime.HEARTBEAT_MIN_INTERVAL
            self.assertTrue(relay.send_heartbeat("connector-a", "offline"))

        self.assertEqual(calls, [(100.0, "online"), (110.0, "offline"),
                                 (150.0, "offline")])

    def test_failed_outbox_delivery_does_not_extend_offline_heartbeat(self):
        message = self.event("queued")
        self.db.execute(
            "INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,1)",
            ("connector-a", "primary", "queued", runtime.compact(message)),
        )
        self.db.commit()
        calls = []

        def http(method, path, payload=None):
            calls.append((method, path, payload))
            if path.endswith("/events"):
                raise OSError("relay unavailable")
            return {"ok": True, "commands": []}

        relay = runtime.Relay(self.config, self.db, lambda _request: {}, http)
        with patch.object(runtime.time, "monotonic", return_value=1000.0):
            relay.pass_once()

        heartbeat = next(payload for _method, path, payload in calls if path.endswith("/heartbeat"))
        self.assertEqual(heartbeat["state"], "offline")
        self.assertFalse(relay.health["connector-a"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)
        self.assertFalse(any(method == "GET" and path.startswith("/api/connectors/commands")
                             for method, path, _payload in calls))

    def test_outbox_progress_is_attributed_only_to_acknowledged_connector(self):
        self.config["connectors"] = [
            {"id": "connector-a", "token": "a" * 40, "profile": "primary",
             "kind": "qq", "accountLabel": "A", "displayName": "A"},
            {"id": "connector-b", "token": "b" * 40, "profile": "primary",
             "kind": "wechat", "accountLabel": "B", "displayName": "B"},
        ]
        for connector_id in ("connector-a", "connector-b"):
            for index in range(runtime.MAX_DELIVERIES_PER_PASS * runtime.MAX_OUTBOX_BATCH_MESSAGES + 1):
                message = self.event(connector_id + "-" + str(index))
                self.db.execute(
                    "INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,1)",
                    (connector_id, "primary", connector_id + "-" + str(index), runtime.compact(message)),
                )
        self.db.commit()
        heartbeats = {}

        def http(method, path, payload=None):
            if path.endswith("/events") and payload["connectorId"] == "connector-b":
                raise OSError("connector B unavailable")
            if path.endswith("/heartbeat"):
                heartbeats[payload["connectorId"]] = payload["state"]
            if path == "/api/connectors/events":
                return self.event_ack(len(payload["messages"]))
            return {"ok": True, "commands": []}

        relay = runtime.Relay(self.config, self.db, lambda _request: {}, http)
        with patch.object(runtime.time, "monotonic", return_value=1000.0):
            relay.pass_once()

        self.assertEqual(heartbeats, {"connector-a": "online", "connector-b": "offline"})
        self.assertFalse(relay.health["connector-a"])
        self.assertFalse(relay.health["connector-b"])

    def test_heartbeat_failure_uses_independent_bounded_backoff(self):
        heartbeat_calls = []
        now = [1000.0]

        def adapter(_request):
            return {"ok": True, "sourceReadOk": True, "health": "online", "active": False,
                    "cursor": None, "messages": []}

        def http(method, path, payload=None):
            if path.endswith("/heartbeat"):
                heartbeat_calls.append(now[0])
                if len(heartbeat_calls) == 1:
                    raise OSError("heartbeat unavailable")
            return {"ok": True, "commands": []}

        relay = runtime.Relay(self.config, self.db, adapter, http)
        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]):
            relay.pass_once()
            self.assertEqual(relay.retry_at["connector-a"], 0)
            self.assertEqual(relay.heartbeat_retry_at["connector-a"], now[0] + 15)
            now[0] += 5
            relay.pass_once()
            self.assertEqual(heartbeat_calls, [1000.0])
            now[0] += 10
            relay.pass_once()

        self.assertEqual(heartbeat_calls, [1000.0, 1015.0])
        self.assertEqual(relay.heartbeat_retry_at["connector-a"], 0)
        self.assertEqual(relay.heartbeat_failures["connector-a"], 0)
        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]):
            expected_delays = [15, 30, 60, 60]
            for delay in expected_delays:
                relay.heartbeat_failed("connector-a")
                self.assertEqual(relay.heartbeat_retry_at["connector-a"] - now[0], delay)
                now[0] += delay

    def test_pending_more_scan_uses_fifteen_seconds_then_returns_to_active_or_idle_interval(self):
        scans = []
        now = [1000.0]
        results = [
            {"ok": True, "sourceReadOk": True, "health": "online", "active": False, "more": True,
             "cursor": None, "messages": []},
            {"ok": True, "sourceReadOk": True, "health": "online", "active": False,
             "cursor": None, "messages": []},
            {"ok": True, "sourceReadOk": True, "health": "online", "active": True, "more": False,
             "cursor": None, "messages": []},
        ]
        relay = runtime.Relay(
            self.config, self.db,
            lambda request: scans.append(request) or results.pop(0),
            lambda *args: {"ok": True, "commands": []})
        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]):
            relay.pass_once()
            self.assertEqual(relay.scan_interval["connector-a"], 15)
            now[0] += 14
            relay.pass_once()
            self.assertEqual(len(scans), 1)
            now[0] += 1
            relay.pass_once()
            self.assertEqual(relay.scan_interval["connector-a"], 300)
            now[0] += 299
            relay.pass_once()
            self.assertEqual(len(scans), 2)
            now[0] += 1
            relay.pass_once()
            self.assertEqual(relay.scan_interval["connector-a"], 60)
        self.assertEqual(len(scans), 3)

    def test_first_scan_is_immediate_when_monotonic_clock_starts_at_zero(self):
        scans = []
        relay = runtime.Relay(self.config, self.db,
                              lambda request: scans.append(request) or {
                                  "ok": True, "sourceReadOk": True, "health": "online", "active": False,
                                  "cursor": None, "messages": []},
                              lambda *args: {"ok": True, "commands": []})
        with patch.object(runtime.time, "monotonic", return_value=0):
            relay.pass_once()
        self.assertEqual(len(scans), 1)

    def test_redirect_handler_refuses_credential_redirect(self):
        request = runtime.urllib.request.Request("https://worker.example/api/connectors/events")
        with self.assertRaises(runtime.urllib.error.HTTPError):
            runtime.NoRedirect().redirect_request(request, None, 302, "Found", {}, "https://other.example/")

    def test_http_request_sends_device_headers_and_connector_identity(self):
        received = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                received["path"] = self.path
                received["headers"] = self.headers
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def log_message(self, _format, *_args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            relay = runtime.Relay(self.config, self.db, lambda _request: {}, None)
            relay.base = "http://127.0.0.1:%d" % server.server_port
            relay.select_connector(self.config["connectors"][0])
            result = relay.request("GET", "/api/connectors/healthz")
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(result, {"ok": True})
        self.assertEqual(received["path"], "/api/connectors/healthz")
        self.assertEqual(received["headers"].get("User-Agent"), "MessageCenterDevice/1.0")
        self.assertEqual(received["headers"].get("Accept"), "application/json")
        self.assertEqual(received["headers"].get("Authorization"), "Bearer " + "x" * 40)
        self.assertEqual(received["headers"].get("X-connector-id"), "connector-a")

    def auto_wake_config(self):
        config = dict(self.config)
        config["autoWake"] = True
        config["connectors"] = [
            {**self.config["connectors"][0], "kind": "qq"},
            {"id": "connector-b", "token": "y" * 40, "kind": "qq",
             "accountLabel": "test", "displayName": "device", "profile": "secondary"},
        ]
        return config

    def wake_result(self, ready=True):
        return {"ok": True, "ready": ready, "attempted": not ready, "reason": "ready" if ready else "locked"}

    def test_auto_wake_is_bounded_to_once_per_minute(self):
        calls = []
        relay = runtime.Relay(self.auto_wake_config(), self.db,
                              lambda req: calls.append(req) or self.wake_result())
        with patch.object(runtime.time, "monotonic", return_value=100):
            self.assertTrue(relay.ensure_active())
        with patch.object(runtime.time, "monotonic", return_value=159.999):
            self.assertTrue(relay.ensure_active())
        with patch.object(runtime.time, "monotonic", return_value=160):
            self.assertTrue(relay.ensure_active())
        self.assertEqual(calls, [{"op": "ensure-active", "driver": "qq"},
                                 {"op": "ensure-active", "driver": "qq"}])
        self.assertEqual(runtime.adapter_timeout_for_request({"op": "ensure-active"}), 55)

    def test_auto_wake_invalid_and_exception_results_fail_closed(self):
        responses = [
            {"ok": True, "ready": True, "attempted": True, "reason": "x" * 41},
            {"ok": True, "ready": True, "attempted": True, "reason": "ready"},
            {"ok": True, "ready": 1, "attempted": True, "reason": "ready"},
            RuntimeError("adapter_timeout"),
        ]
        for response in responses:
            def adapter(_request, response=response):
                if isinstance(response, Exception):
                    raise response
                return response
            relay = runtime.Relay(self.auto_wake_config(), self.db, adapter)
            with patch.object(runtime.time, "monotonic", return_value=100):
                self.assertFalse(relay.ensure_active())
            self.assertFalse(relay.wake_ready)

    def test_auto_wake_logs_only_changed_state_tuples(self):
        responses = [self.wake_result(False), self.wake_result(True)]
        calls = []
        def adapter(request):
            calls.append(request)
            return responses.pop(0)
        relay = runtime.Relay(self.auto_wake_config(), self.db, adapter)
        captured = io.StringIO()
        with redirect_stderr(captured):
            with patch.object(runtime.time, "monotonic", return_value=100):
                self.assertFalse(relay.ensure_active())
            with patch.object(runtime.time, "monotonic", return_value=120):
                self.assertFalse(relay.ensure_active())
            with patch.object(runtime.time, "monotonic", return_value=160):
                self.assertTrue(relay.ensure_active())
        records = [json.loads(line) for line in captured.getvalue().splitlines()]
        self.assertEqual(len(calls), 2)
        self.assertEqual([(record["ready"], record["attempted"], record["reason"])
                          for record in records], [(False, True, "locked"), (True, False, "ready")])
        self.assertTrue(all(record["observedAt"].endswith("Z") for record in records))
        self.assertTrue(all(set(record) == {"observedAt", "ready", "attempted", "reason"}
                            for record in records))

    def test_auto_wake_diagnostic_errors_use_fixed_reasons(self):
        class TrackingStderr(io.StringIO):
            def __init__(self):
                super().__init__()
                self.flush_calls = 0

            def flush(self):
                self.flush_calls += 1
                super().flush()

        for response, expected in (({}, "invalid_schema"),
                                   (RuntimeError("adapter_timeout"), "timeout"),
                                   (RuntimeError("adapter_failed"), "subprocess_failed"),
                                   (RuntimeError("adapter_invalid_response"), "invalid_schema"),
                                   (RuntimeError("adapter_response_too_large"), "response_too_large"),
                                   (RuntimeError("adapter_spawn_failed"), "spawn_error"),
                                   (OSError("private path detail"), "io_error"),
                                   (json.JSONDecodeError("private parse detail", "secret", 0), "invalid_json"),
                                   (RuntimeError("private error detail"), "adapter_error")):
            def adapter(_request, response=response):
                if isinstance(response, Exception):
                    raise response
                return response
            relay = runtime.Relay(self.auto_wake_config(), self.db, adapter)
            captured = TrackingStderr()
            with redirect_stderr(captured), patch.object(runtime.time, "monotonic", return_value=100):
                self.assertFalse(relay.ensure_active())
            record = json.loads(captured.getvalue())
            self.assertEqual(record["reason"], expected)
            self.assertEqual(captured.flush_calls, 1)
            self.assertNotIn("private", captured.getvalue())

    def test_auto_wake_not_ready_skips_scans_and_command_polls_but_flushes_outbox(self):
        adapter_calls = []
        http_calls = []
        relay = runtime.Relay(self.auto_wake_config(), self.db,
                              lambda req: adapter_calls.append(req) or self.wake_result(False),
                              lambda method, path, payload=None: http_calls.append((method, path)) or
                                  (self.event_ack(1) if path.endswith("/events") else {"ok": True}))
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,?)",
                         ("connector-a", "primary", "queued", runtime.compact(self.event("queued")), 100))
        self.db.commit()
        with patch.object(runtime.time, "monotonic", return_value=1000):
            relay.pass_once()
        self.assertEqual(adapter_calls, [{"op": "ensure-active", "driver": "qq"}])
        self.assertFalse(any("/commands?" in path for _, path in http_calls))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)
        self.assertEqual(sum(path.endswith("/events") for _, path in http_calls), 1)
        self.assertEqual(sum(path.endswith("/heartbeat") for _, path in http_calls), 2)

    def test_auto_wake_expired_during_outbox_flush_gates_scans_and_command_polls(self):
        now = [100]
        adapter_calls = []
        http_calls = []

        def adapter(request):
            adapter_calls.append(request)
            if request["op"] == "ensure-active":
                return self.wake_result(len([item for item in adapter_calls
                                             if item["op"] == "ensure-active"]) == 1)
            raise AssertionError("scan must remain gated after fresh readiness is false")

        def http_call(method, path, payload=None):
            http_calls.append(path)
            if path.endswith("/events"):
                now[0] += 61
                return self.event_ack(1)
            return {"ok": True}
        relay = runtime.Relay(self.auto_wake_config(), self.db, adapter, http_call)
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,?)",
                         ("connector-a", "primary", "queued", runtime.compact(self.event("queued")), 100))
        self.db.commit()
        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]):
            relay.pass_once()
        self.assertEqual(adapter_calls, [{"op": "ensure-active", "driver": "qq"},
                                         {"op": "ensure-active", "driver": "qq"}])
        self.assertEqual(sum(path.endswith("/events") for path in http_calls), 1)
        self.assertFalse(any("/commands?" in path for path in http_calls))
        self.assertEqual(sum(path.endswith("/heartbeat") for path in http_calls), 2)

    def test_slow_scan_and_profile_sync_refresh_readiness_before_online_and_command_gate(self):
        now = [100.0]
        adapter_calls = []
        http_calls = []

        def adapter(request):
            adapter_calls.append(request)
            if request["op"] == "ensure-active":
                return self.wake_result(True)
            now[0] += 35
            return {"ok": True, "sourceReadOk": True, "health": "online",
                    "cursor": None, "messages": [],
                    "conversationProfiles": [{"conversationExternalId": "conversation-aaaaaaaa",
                                               "displayName": "Test"}],
                    "senderAvatars": [{"id": "sender-a", "sha256": "a" * 64}]}

        def http(method, path, payload=None):
            http_calls.append((now[0], method, path, payload))
            return {"ok": True, "commands": []}

        relay = runtime.Relay(self.auto_wake_config(), self.db, adapter, http)
        relay.connectors = relay.connectors[:1]
        relay.connector_by_id = {relay.connectors[0]["id"]: relay.connectors[0]}
        relay.health["connector-a"] = True
        relay.wake_ready = True
        relay.wake_readiness_established = True
        relay.wake_ready_at = now[0]
        relay.last_wake_attempt = now[0]

        def slow_profile_sync(*_args):
            now[0] += 20

        def slow_avatar_sync(*_args):
            now[0] += 20

        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]), \
                patch.object(runtime, "sync_profiles", side_effect=slow_profile_sync), \
                patch.object(runtime, "sync_sender_avatars", side_effect=slow_avatar_sync):
            relay.pass_once()

        self.assertEqual(sum(item["op"] == "ensure-active" for item in adapter_calls), 1)
        self.assertEqual(sum(item["op"] == "scan" for item in adapter_calls), 1)
        heartbeats = [row for row in http_calls if row[2].endswith("/heartbeat")]
        self.assertEqual([row[3]["state"] for row in heartbeats], ["online"])
        self.assertTrue(any(row[1] == "GET" and "/commands?" in row[2] for row in http_calls))

    def test_slow_scan_with_fresh_not_ready_result_stays_offline_and_gates_commands(self):
        now = [100.0]
        adapter_calls = []
        http_calls = []

        def adapter(request):
            adapter_calls.append(request)
            if request["op"] == "ensure-active":
                return self.wake_result(False)
            now[0] += 70
            return {"ok": True, "sourceReadOk": True, "health": "online",
                    "cursor": None, "messages": []}

        def http(method, path, payload=None):
            http_calls.append((method, path, payload))
            return {"ok": True, "commands": []}

        relay = runtime.Relay(self.auto_wake_config(), self.db, adapter, http)
        relay.connectors = relay.connectors[:1]
        relay.connector_by_id = {relay.connectors[0]["id"]: relay.connectors[0]}
        relay.health["connector-a"] = True
        relay.wake_ready = True
        relay.wake_readiness_established = True
        relay.wake_ready_at = now[0]
        relay.last_wake_attempt = now[0]

        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]):
            relay.pass_once()

        self.assertEqual(sum(item["op"] == "ensure-active" for item in adapter_calls), 1)
        self.assertEqual(sum(item["op"] == "scan" for item in adapter_calls), 1)
        heartbeat = next(payload for _method, path, payload in http_calls if path.endswith("/heartbeat"))
        self.assertEqual(heartbeat["state"], "offline")
        self.assertFalse(any(method == "GET" and "/commands?" in path
                             for method, path, _payload in http_calls))

    def test_auto_wake_recovery_forces_fresh_scan_without_clearing_cloud_backoff(self):
        scans = []
        http_calls = []
        now = [1000.0]
        def adapter(req):
            if req["op"] == "ensure-active":
                return self.wake_result(True)
            scans.append(req)
            return {"ok": True, "sourceReadOk": True, "health": "online", "cursor": None, "messages": []}
        relay = runtime.Relay(self.auto_wake_config(), self.db, adapter,
                              lambda method, path, payload=None: http_calls.append(path) or {"ok": True})
        relay.wake_ready = False
        relay.last_wake_attempt = 0
        relay.last_scan.update({"connector-a": 990, "connector-b": 990})
        relay.scan_interval.update({"connector-a": 300, "connector-b": 300})
        relay.wake_scan_retry_at["connector-a"] = 5000
        relay.retry_at["connector-a"] = 5000
        relay.failures["connector-a"] = 4
        with patch.object(runtime.time, "monotonic", side_effect=lambda: now[0]), patch.object(
            runtime.time, "time", side_effect=lambda: now[0]
        ):
            relay.pass_once()
            self.assertEqual(scans, [])
            now[0] += 60
            relay.pass_once()
        self.assertEqual([request["driver"] for request in scans], ["qq", "qq"])
        self.assertEqual(relay.retry_at["connector-a"], 5000)
        self.assertEqual(relay.failures["connector-a"], 4)
        self.assertTrue(all(request.get("history") is False for request in scans))

    def test_auto_wake_accepts_qq_only_and_rejects_mixed_connectors(self):
        config = self.auto_wake_config()
        config["connectors"] = config["connectors"][:1]
        runtime.Relay(config, self.db, lambda _request: {})
        config = self.auto_wake_config()
        config["connectors"][1]["kind"] = "wechat"
        with self.assertRaisesRegex(ValueError, "auto_wake_requires_qq_only"):
            runtime.Relay(config, self.db, lambda _request: {})

    def test_auto_wake_omitted_preserves_existing_scan_and_command_behavior(self):
        scans = []
        http_calls = []
        relay = runtime.Relay(self.config, self.db,
                              lambda req: scans.append(req) or {"ok": True, "sourceReadOk": True, "health": "online",
                                  "cursor": None, "messages": []},
                              lambda method, path, payload=None: http_calls.append(path) or {"ok": True})
        with patch.object(runtime.time, "monotonic", return_value=1000):
            relay.pass_once()
        self.assertEqual(len(scans), 1)
        self.assertEqual(scans[0]["op"], "scan")
        self.assertTrue(any("/commands?" in path for path in http_calls))


def json_cursor(db):
    return db.execute("SELECT value FROM cursors WHERE connector_id='connector-a' AND profile='primary'").fetchone()[0]


if __name__ == "__main__":
    unittest.main()
