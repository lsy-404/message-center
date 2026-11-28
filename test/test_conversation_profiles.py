import base64
import hashlib
import importlib.util
import json
import os
import sqlite3
import unittest
import urllib.parse


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "bridge", "device-runtime", "conversation_profiles.py")
SPEC = importlib.util.spec_from_file_location("conversation_profiles", SOURCE)
profiles_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profiles_module)


class FakeRelay:
    connector = "connector-test"

    def __init__(self, outcomes=None):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE sync_digests(connector_id TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL,"
                        " digest TEXT NOT NULL, PRIMARY KEY(connector_id,kind,key))")
        self.outcomes = list(outcomes) if outcomes is not None else None
        self.calls = []

    def api_call(self, method, path, headers, body):
        self.calls.append((method, path, headers, body))
        if self.outcomes is None:
            return 200, '{"ok":true}'
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class ConversationProfileTests(unittest.TestCase):
    def request_with(self, profiles):
        relay = FakeRelay()
        result = profiles_module.sync_profiles(relay, profiles)
        return result, relay

    def test_put_uses_worker_headers_utf8_percent_encoding_and_empty_body(self):
        profile = {
            "conversationExternalId": "group:fixture-1",
            "displayName": "群聊 Café",
            "channelLabel": "即时 消息",
            "conversationType": "group",
            "placement": "folded",
            "pinned": True,
            "unreadCount": 17,
            "unreadObservedAt": "2026-10-07T12:00:00.000Z",
            "lastMessagePreview": "最新消息 🌱",
            "lastMessageAt": "2026-10-07T12:01:00+00:00",
        }
        result, relay = self.request_with([profile])
        self.assertEqual(result, 1)
        method, path, headers, body = relay.calls[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(path, "/api/connectors/conversation-profiles/group:fixture-1")
        self.assertEqual(body, b"")
        self.assertNotIn("Content-Type", headers)
        self.assertEqual(urllib.parse.unquote(headers["x-conversation-display-name"]), "群聊 Café")
        self.assertEqual(urllib.parse.unquote(headers["x-conversation-channel-label"]), "即时 消息")
        self.assertEqual(urllib.parse.unquote(headers["x-conversation-last-preview"]), "最新消息 🌱")
        self.assertEqual(headers["x-conversation-type"], "group")
        self.assertEqual(headers["x-conversation-placement"], "folded")
        self.assertEqual(headers["x-conversation-pinned"], "1")
        self.assertEqual(headers["x-conversation-unread-count"], "17")
        self.assertEqual(headers["x-conversation-unread-observed-at"], "2026-10-07T12:00:00.000Z")
        self.assertEqual(headers["x-conversation-last-at"], "2026-10-07T12:01:00.000Z")

    def test_empty_batch_does_not_open_network(self):
        relay = FakeRelay()
        self.assertEqual(profiles_module.sync_profiles(relay, []), 0)
        self.assertEqual(relay.calls, [])

    def test_profile_count_is_bounded_and_all_metadata_validated_before_requests(self):
        valid = {"conversationExternalId": "group-1", "displayName": "Group"}
        invalid_profiles = [
            [valid] * 21,
            [{**valid, "conversationExternalId": "bad/path"}],
            [{**valid, "displayName": "😀" * 101}],
            [{**valid, "conversationType": []}],
            [{**valid, "placement": "hidden"}],
            [{**valid, "pinned": 1}],
            [{**valid, "unreadCount": True}],
            [{**valid, "unreadObservedAt": "2026-10-07T12:00:00Z"}],
            [{**valid, "lastMessagePreview": "x" * 501}],
            [{**valid, "unreadCount": 1, "unreadObservedAt": "2026-10-07T12:00:00"}],
        ]
        for profiles in invalid_profiles:
            with self.subTest(profiles=profiles[:1]):
                relay = FakeRelay()
                with self.assertRaises(profiles_module.ProfileSyncError):
                    profiles_module.sync_profiles(relay, profiles)
                self.assertEqual(relay.calls, [])

    def test_request_failure_propagates_and_stops_batch(self):
        relay = FakeRelay([(200, '{"ok":true}'), OSError("offline"), (200, '{"ok":true}')])
        with self.assertRaisesRegex(profiles_module.ProfileSyncError, "profile_request_failed"):
            profiles_module.sync_profiles(relay, [
                {"conversationExternalId": "group-1", "displayName": "Group 1"},
                {"conversationExternalId": "group-2", "displayName": "Group 2"},
                {"conversationExternalId": "group-3", "displayName": "Group 3"},
            ])
        self.assertEqual(len(relay.calls), 2)

    def test_worker_rejection_is_not_acknowledged_as_success(self):
        for outcome in ((200, '{"ok":false,"error":"invalid_conversation_profile"}'), (400, '{"ok":true}')):
            relay = FakeRelay([outcome])
            with self.assertRaisesRegex(profiles_module.ProfileSyncError, "profile_update_rejected"):
                profiles_module.sync_profiles(relay, [
                    {"conversationExternalId": "group-1", "displayName": "Group"}
                ])

    def test_sender_avatar_rejection_is_reported(self):
        encoded = base64.b64encode(b"\x89PNG\r\n\x1a\nsender-avatar").decode("ascii")
        relay = FakeRelay([(200, '{"ok":true}'), (200, '{"ok":false}')])
        with self.assertRaisesRegex(profiles_module.ProfileSyncError, "sender_avatar_update_rejected"):
            profiles_module.sync_sender_avatars(relay, [
                {"senderId": "sender-1", "avatarBase64": encoded},
                {"senderId": "sender-2", "avatarBase64": encoded},
            ])

    def test_valid_png_avatar_puts_raw_bytes_with_worker_headers(self):
        avatar = b"\x89PNG\r\n\x1a\nsynthetic-png"
        profile = {
            "conversationExternalId": "group-1",
            "displayName": "Group",
            "avatarBase64": base64.b64encode(avatar).decode("ascii"),
        }
        result, relay = self.request_with([profile])
        _method, _path, headers, body = relay.calls[0]
        self.assertEqual(result, 1)
        self.assertEqual(body, avatar)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(headers["x-content-sha256"], hashlib.sha256(avatar).hexdigest())

    def test_missing_and_empty_avatar_keep_metadata_only_put(self):
        profiles = [
            {"conversationExternalId": "group-1", "displayName": "Group 1"},
            {"conversationExternalId": "group-2", "displayName": "Group 2", "avatarBase64": ""},
        ]
        result, relay = self.request_with(profiles)
        self.assertEqual(result, 2)
        for _method, _path, headers, body in relay.calls:
            self.assertEqual(body, b"")
            self.assertNotIn("Content-Type", headers)
            self.assertNotIn("x-content-sha256", headers)

    def test_avatar_base64_is_strict_and_full_batch_is_prevalidated(self):
        avatar = b"\x89PNG\r\n\x1a\nsynthetic-png"
        profiles = [
            {"conversationExternalId": "group-1", "displayName": "Group 1",
             "avatarBase64": base64.b64encode(avatar).decode("ascii")},
            {"conversationExternalId": "group-2", "displayName": "Group 2", "avatarBase64": "%%%="},
        ]
        relay = FakeRelay()
        with self.assertRaisesRegex(profiles_module.ProfileSyncError, "invalid_profile_avatar"):
            profiles_module.sync_profiles(relay, profiles)
        self.assertEqual(relay.calls, [])

    def test_avatar_per_image_and_batch_decoded_caps_are_enforced_before_network(self):
        def png(size):
            return b"\x89PNG\r\n\x1a\n" + b"x" * (size - 8)

        oversized_image = {
            "conversationExternalId": "group-1", "displayName": "Group",
            "avatarBase64": base64.b64encode(png(profiles_module.MAX_AVATAR_BYTES + 1)).decode("ascii"),
        }
        over_batch = [
            {"conversationExternalId": "group-1", "displayName": "Group 1",
             "avatarBase64": base64.b64encode(png(64 * 1024)).decode("ascii")},
            {"conversationExternalId": "group-2", "displayName": "Group 2",
             "avatarBase64": base64.b64encode(png(64 * 1024 + 1)).decode("ascii")},
        ]
        for profiles in ([oversized_image], over_batch):
            with self.subTest(count=len(profiles)):
                relay = FakeRelay()
                with self.assertRaisesRegex(profiles_module.ProfileSyncError, "profile_avatar_too_large"):
                    profiles_module.sync_profiles(relay, profiles)
                self.assertEqual(relay.calls, [])

    def test_invalid_avatar_magic_is_rejected_before_network(self):
        profile = {
            "conversationExternalId": "group-1", "displayName": "Group",
            "avatarBase64": base64.b64encode(b"not-an-image").decode("ascii"),
        }
        relay = FakeRelay()
        with self.assertRaisesRegex(profiles_module.ProfileSyncError, "invalid_profile_avatar"):
            profiles_module.sync_profiles(relay, [profile])
        self.assertEqual(relay.calls, [])

    def test_sender_avatar_put_uses_raw_bytes_and_connector_auth_headers(self):
        avatar = b"\x89PNG\r\n\x1a\nsynthetic-sender"
        item = {"senderId": "qq:sender-1", "avatarBase64": base64.b64encode(avatar).decode("ascii")}
        relay = FakeRelay()
        self.assertEqual(profiles_module.sync_sender_avatars(relay, [item]), 1)
        method, path, headers, body = relay.calls[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(path, "/api/connectors/sender-avatars/qq:sender-1")
        self.assertEqual(body, avatar)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(headers["x-content-sha256"], hashlib.sha256(avatar).hexdigest())

    def test_sender_avatar_empty_batch_or_empty_images_do_not_open_network(self):
        for avatars in ([], [{"senderId": "sender-1", "avatarBase64": ""}],
                        [{"senderId": "sender-1"}]):
            with self.subTest(avatars=avatars):
                relay = FakeRelay()
                self.assertEqual(profiles_module.sync_sender_avatars(relay, avatars), 0)
                self.assertEqual(relay.calls, [])

    def test_sender_avatar_batches_are_fully_validated_and_bounded_before_network(self):
        png = lambda size: b"\x89PNG\r\n\x1a\n" + b"x" * (size - 8)
        invalid_batches = [
            [{"senderId": "sender-1", "avatarBase64": "%%%="}],
            [{"senderId": "sender-1", "avatarBase64": base64.b64encode(b"not-image").decode()}],
            [{"senderId": "bad/id", "avatarBase64": base64.b64encode(png(12)).decode()}],
            [{"senderId": "sender-1", "avatarBase64": base64.b64encode(png(profiles_module.MAX_AVATAR_BYTES + 1)).decode()}],
            [
                {"senderId": "sender-1", "avatarBase64": base64.b64encode(png(64 * 1024)).decode()},
                {"senderId": "sender-2", "avatarBase64": base64.b64encode(png(64 * 1024 + 1)).decode()},
            ],
            [{"senderId": "sender-%d" % index} for index in range(profiles_module.MAX_PROFILES + 1)],
        ]
        for avatars in invalid_batches:
            with self.subTest(count=len(avatars)):
                relay = FakeRelay()
                with self.assertRaises(profiles_module.ProfileSyncError):
                    profiles_module.sync_sender_avatars(relay, avatars)
                self.assertEqual(relay.calls, [])


if __name__ == "__main__":
    unittest.main()
