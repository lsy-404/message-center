import importlib.util
import os
import sqlite3
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "bridge", "device-runtime", "device_runtime.py")
SPEC = importlib.util.spec_from_file_location("device_runtime", SOURCE)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class DeviceRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "runtime.sqlite3")
        self.config = {
            "serviceUrl": "https://worker.example",
            "database": self.db_path,
            "adapter": "unused-private-adapter",
            "connectors": [{"id": "connector-a", "token": "x" * 40,
                            "kind": "im", "accountLabel": "test", "displayName": "device",
                            "profile": "primary"}],
            "outboxMaxBytes": 100000,
            "pageLimit": 20,
        }
        self.db = runtime.open_database(self.db_path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def event(self, ident):
        return {"externalId": ident, "conversationExternalId": "conversation-1",
                "conversationTitle": "Test", "senderName": "Sender",
                "occurredAt": "2026-10-07T12:00:00.000Z", "body": ident}

    def test_offline_spool_survives_restart_and_response_loss_reuses_event_id(self):
        calls = []
        def scan(_request):
            return {"ok": True, "health": "online", "cursor": {"next": "2"},
                    "messages": [self.event("stable-1")]}
        def lose_response(method, path, payload=None):
            calls.append((method, path, payload))
            if path.endswith("/events"):
                raise OSError("connection lost after request")
            return {"ok": True}
        first = runtime.Relay(self.config, self.db, scan, lose_response)
        first.scan_profile("primary")
        with self.assertRaises(OSError):
            first.flush_one()
        saved = self.db.execute("SELECT external_id FROM outbox").fetchone()[0]
        self.assertEqual(saved, "stable-1")
        self.db.close()

        db2 = runtime.open_database(self.db_path)
        try:
            success_calls = []
            relay = runtime.Relay(self.config, db2, scan,
                                  lambda method, path, payload=None: success_calls.append(payload) or {"ok": True})
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
                              lambda req: calls.append(req) or {"ok": True, "health": "online",
                                  "cursor": {"next": "new"}, "messages": [self.event("next")]},
                              lambda *args: {"ok": True})
        self.assertFalse(relay.scan_profile("primary"))
        self.assertEqual(json_cursor(self.db), old)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)

    def test_page_that_would_exceed_capacity_does_not_advance_cursor(self):
        old = runtime.compact({"next": "old"})
        self.db.execute("INSERT INTO cursors(connector_id,profile,value) VALUES('connector-a','primary',?)", (old,))
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) "
                        "VALUES('connector-a','primary','existing','{}',10)")
        self.db.commit()
        self.config["outboxMaxBytes"] = 100
        relay = runtime.Relay(self.config, self.db,
                              lambda req: {"ok": True, "health": "online", "cursor": {"next": "new"},
                                           "messages": [dict(self.event("next"), body="x" * 150)]},
                              lambda *args: {"ok": True})
        self.assertIsNone(relay.scan_profile("primary"))
        self.assertEqual(json_cursor(self.db), old)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)

    def test_unsupported_attachment_page_does_not_commit_cursor(self):
        old = runtime.compact({"next": "old"})
        self.db.execute("INSERT INTO cursors(connector_id,profile,value) VALUES('connector-a','primary',?)", (old,))
        self.db.commit()
        relay = runtime.Relay(self.config, self.db,
                              lambda req: {"ok": True, "health": "online", "cursor": {"next": "new"},
                                           "messages": [dict(self.event("file"), attachments=[{"externalId": "f"}])]},
                              lambda *args: {"ok": True})
        with self.assertRaisesRegex(RuntimeError, "adapter_file_receive_not_supported"):
            relay.scan_profile("primary")
        self.assertEqual(json_cursor(self.db), old)

    def test_page_that_would_exceed_capacity_does_not_advance_cursor(self):
        old = runtime.compact({"next": "old"})
        self.db.execute("INSERT INTO cursors(connector_id,profile,value) VALUES('connector-a','primary',?)", (old,))
        self.db.execute("INSERT INTO outbox(connector_id,profile,external_id,body,size) "
                        "VALUES('connector-a','primary','existing','{}',10)")
        self.db.commit()
        self.config["outboxMaxBytes"] = 100
        relay = runtime.Relay(self.config, self.db,
                              lambda req: {"ok": True, "health": "online", "cursor": {"next": "new"},
                                           "messages": [dict(self.event("next"), body="x" * 150)]},
                              lambda *args: {"ok": True})
        self.assertIsNone(relay.scan_profile("primary"))
        self.assertEqual(json_cursor(self.db), old)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)

    def test_scan_commits_cursor_atomically_with_durable_outbox(self):
        relay = runtime.Relay(self.config, self.db,
                              lambda req: {"ok": True, "health": "online", "cursor": {"n": 3},
                                           "messages": [self.event("next")]},
                              lambda *args: {"ok": True})
        self.assertTrue(relay.scan_profile("primary"))
        self.assertEqual(json_cursor(self.db), runtime.compact({"n": 3}))
        self.assertEqual(self.db.execute("SELECT external_id FROM outbox").fetchone()[0], "next")

    def test_two_connector_identities_share_one_sequential_runtime(self):
        self.config["connectors"] = [
            {"id": "connector-a", "token": "a" * 40, "profile": "primary",
             "kind": "im", "accountLabel": "A", "displayName": "A"},
            {"id": "connector-b", "token": "b" * 40, "profile": "secondary",
             "kind": "im", "accountLabel": "B", "displayName": "B"},
        ]
        adapter_profiles = []
        requests = []
        def adapter(request):
            adapter_profiles.append(request["profile"])
            return {"ok": True, "health": "online", "cursor": request["profile"],
                    "messages": [self.event(request["profile"])]}
        def http(method, path, payload=None):
            requests.append((method, path, payload))
            return {"ok": True, "commands": []}
        relay = runtime.Relay(self.config, self.db, adapter, http)
        relay.pass_once()
        relay.pass_once()
        event_ids = [item[2]["connectorId"] for item in requests
                     if item[1].endswith("/events")]
        self.assertEqual(adapter_profiles, ["primary", "secondary"])
        self.assertEqual(event_ids, ["connector-a", "connector-b"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)

    def test_started_send_is_marked_uncertain_without_second_adapter_call(self):
        command = {"id": "command-1", "leaseToken": "lease-1", "idempotencyKey": "key-1",
                   "payload": {"externalConversationId": "conversation-1", "body": "hello"}}
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
        command = {"id": "command-2", "leaseToken": "lease-2", "idempotencyKey": "key-2",
                   "payload": {"externalConversationId": "conversation-1", "body": "hello"}}
        adapter_calls = []
        completion_calls = []
        def adapter(request):
            adapter_calls.append(request)
            return {"ok": True, "receipt": "receipt-2"}
        def http(method, path, payload=None):
            if path.endswith("/complete"):
                completion_calls.append(payload)
            if path.endswith("/complete") and len(completion_calls) == 1:
                raise OSError("completion response lost")
            return {"ok": True}
        relay = runtime.Relay(self.config, self.db, adapter, http)
        with self.assertRaises(OSError):
            relay.process_command(command, "primary")
        relay.process_command(command, "primary")
        self.assertEqual(len(adapter_calls), 1)
        self.assertEqual(completion_calls[0], completion_calls[1])

    def test_invalid_lease_is_checked_before_native_send(self):
        command = {"id": "command-3", "leaseToken": "expired", "idempotencyKey": "key-3",
                   "payload": {"externalConversationId": "conversation-1", "body": "hello"}}
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

    def test_invalid_lease_is_checked_before_native_send(self):
        command = {"id": "command-3", "leaseToken": "expired", "idempotencyKey": "key-3",
                   "payload": {"externalConversationId": "conversation-1", "body": "hello"}}
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


def json_cursor(db):
    return db.execute("SELECT value FROM cursors WHERE connector_id='connector-a' AND profile='primary'").fetchone()[0]


if __name__ == "__main__":
    unittest.main()
