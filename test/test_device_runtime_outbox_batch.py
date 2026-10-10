from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

import test_device_runtime as runtime_test


runtime = runtime_test.runtime


class DeviceRuntimeOutboxBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = os.path.join(self.temp.name, "runtime.sqlite3")
        self.config = {
            "serviceUrl": "https://worker.example",
            "database": self.database,
            "adapter": "unused",
            "connectors": [{"id": "connector-a", "token": "x" * 40,
                            "profile": "primary", "kind": "qq",
                            "accountLabel": "test", "displayName": "device"}],
        }
        self.db = runtime.open_database(self.database)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def event(self, external_id, **updates):
        return {
            "externalId": external_id,
            "conversationExternalId": "primary:conversation-aaaaaaaa",
            "conversationTitle": "Test",
            "senderName": "Sender",
            "occurredAt": "2026-10-07T12:00:00.000Z",
            "contentType": "text",
            "body": external_id,
            **updates,
        }

    def enqueue(self, message, profile="primary", connector_id="connector-a"):
        body = runtime.compact(message)
        self.db.execute(
            "INSERT INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,?)",
            (connector_id, profile, message["externalId"], body,
             len(runtime.compact({"connectorId": connector_id, "messages": [message]}).encode("utf-8"))),
        )
        self.db.commit()

    def event_ack(self, received, **changes):
        return {"ok": True, "received": received, "inserted": received,
                "upgraded": 0, "promoted": 0, "suppressed": 0, **changes}

    def backup_ack(self, received, **changes):
        return {"ok": True, "received": received, "inserted": received,
                "normalizedInserted": received, "retentionDays": 30, **changes}

    def make_relay(self, http):
        return runtime.Relay(self.config, self.db, lambda _request: {}, http)

    def outbox_ids(self):
        return [row[0] for row in self.db.execute(
            "SELECT external_id FROM outbox WHERE connector_id='connector-a' ORDER BY seq")]

    def test_batches_only_contiguous_same_route_prefix_and_accepts_dedupe_counters(self):
        direct_a = self.event("direct-a")
        direct_b = self.event("direct-b")
        group_a = self.event("group-a", conversationType="group", trigger="background")
        group_b = self.event("group-b", conversationType="group", trigger="background")
        direct_c = self.event("direct-c")
        for item in (direct_a, direct_b, group_a, group_b, direct_c):
            self.enqueue(item)
        calls = []

        def http(_method, path, payload=None):
            ids = [item["externalId"] for item in payload["messages"]]
            calls.append((path, ids))
            if path.endswith("group-text-backups"):
                return self.backup_ack(len(ids), inserted=0, normalizedInserted=0)
            return self.event_ack(len(ids), inserted=0, upgraded=1, promoted=1)

        relay = self.make_relay(http)
        self.assertEqual(relay.flush_one(), "connector-a")
        self.assertEqual(calls, [("/api/connectors/events", ["direct-a", "direct-b"])])
        self.assertEqual(self.outbox_ids(), ["group-a", "group-b", "direct-c"])
        self.assertEqual(relay.flush_one(), "connector-a")
        self.assertEqual(relay.flush_one(), "connector-a")
        self.assertEqual(calls[1:], [
            ("/api/connectors/group-text-backups", ["group-a", "group-b"]),
            ("/api/connectors/events", ["direct-c"]),
        ])
        self.assertEqual(self.outbox_ids(), [])

    def test_profile_change_stops_batch_without_reordering_fifo(self):
        first = self.event("profile-a")
        second = self.event("profile-b")
        self.enqueue(first, profile="primary")
        self.enqueue(second, profile="secondary")
        calls = []
        relay = self.make_relay(lambda _method, path, payload=None:
                                calls.append([item["externalId"] for item in payload["messages"]])
                                or self.event_ack(len(payload["messages"])))
        relay.flush_one()
        relay.flush_one()
        self.assertEqual(calls, [["profile-a"], ["profile-b"]])
        self.assertEqual(self.outbox_ids(), [])

    def test_batch_respects_message_and_aggregate_byte_caps(self):
        for index in range(runtime.MAX_OUTBOX_BATCH_MESSAGES + 1):
            self.enqueue(self.event("small-" + str(index)))
        calls = []
        relay = self.make_relay(lambda _method, _path, payload=None:
                                calls.append(payload) or self.event_ack(len(payload["messages"])))
        relay.flush_one()
        self.assertEqual(len(calls[0]["messages"]), runtime.MAX_OUTBOX_BATCH_MESSAGES)
        relay.flush_one()
        self.assertEqual(len(calls[1]["messages"]), 1)

        self.db.execute("DELETE FROM outbox")
        self.db.commit()
        large_body = "x" * 80_000
        for index in range(12):
            self.enqueue(self.event("large-" + str(index), body=large_body))
        calls.clear()
        relay.flush_one()
        payload_bytes = len(runtime.compact(calls[0]).encode("utf-8"))
        self.assertGreater(len(calls[0]["messages"]), 1)
        self.assertLess(len(calls[0]["messages"]), 12)
        self.assertLessEqual(payload_bytes, runtime.MAX_OUTBOX_BATCH_BYTES)
        self.assertEqual(len(self.outbox_ids()), 12 - len(calls[0]["messages"]))

    def test_attachment_row_keeps_single_upload_path_and_blocks_following_batch(self):
        text_before = self.event("before")
        attachment = {"externalId": "file-1", "fileName": "image.png", "mimeType": "image/png",
                      "sizeBytes": 1, "sha256": "a" * 64, "stagingKey": "stage-1"}
        image_event = self.event("image", attachments=[attachment])
        text_after = self.event("after")
        for item in (text_before, image_event, text_after):
            self.enqueue(item)
        relay = self.make_relay(lambda *_args: self.event_ack(1))
        uploaded = []
        relay.upload_attachment = lambda message, item: uploaded.append(
            (message["externalId"], item["externalId"]))
        calls = []
        relay.http_call = lambda _method, path, payload=None: calls.append(
            (path, payload)) or self.event_ack(len(payload["messages"]))
        relay.flush_one()
        relay.flush_one()
        relay.flush_one()
        self.assertEqual([len(payload["messages"]) for _, payload in calls], [1, 1, 1])
        self.assertEqual([[m["externalId"] for m in payload["messages"]] for _, payload in calls],
                         [["before"], ["image"], ["after"]])
        self.assertEqual(uploaded, [("image", "file-1")])
        self.assertNotIn("stagingKey", calls[1][1]["messages"][0]["attachments"][0])

    def test_wrong_or_partial_ack_keeps_whole_prefix_for_same_id_replay(self):
        for ident in ("retry-a", "retry-b", "retry-c"):
            self.enqueue(self.event(ident))
        ack_failures = [
            self.event_ack(2),
            self.event_ack(3, suppressed=1),
            self.event_ack(3, suppressed=True),
            self.event_ack(3, upgraded=True),
        ]
        relay = self.make_relay(lambda *_args: {})
        calls = []
        for ack in ack_failures:
            relay.retry_at["connector-a"] = 0
            relay.http_call = lambda _method, _path, payload=None, response=ack: calls.append(
                [item["externalId"] for item in payload["messages"]]) or response
            self.assertIsNone(relay.flush_one())
            self.assertEqual(self.outbox_ids(), ["retry-a", "retry-b", "retry-c"])
        relay.retry_at["connector-a"] = 0
        def replay_ack(_method, _path, payload=None):
            calls.append([item["externalId"] for item in payload["messages"]])
            return self.event_ack(3, inserted=0, upgraded=1, promoted=1)
        relay.http_call = replay_ack
        self.assertEqual(relay.flush_one(), "connector-a")
        self.assertEqual(calls, [["retry-a", "retry-b", "retry-c"]] * 5)
        self.assertEqual(self.outbox_ids(), [])

    def test_lost_batch_ack_reopens_sender_database_and_replays_same_ids_once(self):
        for ident in ("lost-a", "lost-b", "lost-c"):
            self.enqueue(self.event(ident))
        accepted = set()
        first_payloads = []

        def server_commits_then_loses_ack(_method, _path, payload=None):
            ids = [item["externalId"] for item in payload["messages"]]
            first_payloads.append(ids)
            accepted.update(ids)
            raise OSError("response lost after server commit")

        first_relay = self.make_relay(server_commits_then_loses_ack)
        self.assertIsNone(first_relay.flush_one())
        self.assertEqual(self.outbox_ids(), ["lost-a", "lost-b", "lost-c"])
        self.db.close()

        self.db = runtime.open_database(self.database)
        replay_payloads = []

        def replay(_method, _path, payload=None):
            ids = [item["externalId"] for item in payload["messages"]]
            replay_payloads.append(ids)
            inserted = 0
            for ident in ids:
                if ident not in accepted:
                    accepted.add(ident)
                    inserted += 1
            return {"ok": True, "received": len(ids), "inserted": inserted,
                    "upgraded": 0, "promoted": 0, "suppressed": 0}

        relay = self.make_relay(replay)
        self.assertEqual(relay.flush_one(), "connector-a")
        self.assertEqual(first_payloads, [["lost-a", "lost-b", "lost-c"]])
        self.assertEqual(replay_payloads, first_payloads)
        self.assertEqual(accepted, {"lost-a", "lost-b", "lost-c"})
        self.assertEqual(self.outbox_ids(), [])

    def test_prefix_delete_rolls_back_if_any_selected_row_changed(self):
        self.enqueue(self.event("atomic-a"))
        self.enqueue(self.event("atomic-b"))

        def ack_then_remove_one(_method, _path, payload=None):
            self.db.execute("DELETE FROM outbox WHERE external_id='atomic-b'")
            self.db.commit()
            return self.event_ack(len(payload["messages"]))

        relay = self.make_relay(ack_then_remove_one)
        with self.assertRaisesRegex(RuntimeError, "outbox_prefix_changed"):
            relay.flush_one()
        self.assertEqual(self.outbox_ids(), ["atomic-a"])


if __name__ == "__main__":
    unittest.main()
