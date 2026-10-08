import base64
import hashlib
import importlib.util
import json
import os
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "bridge", "device-runtime", "conversation_profiles.py")
SPEC = importlib.util.spec_from_file_location("conversation_profiles", SOURCE)
profiles_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profiles_module)


class FakeRelay:
    base = "https://worker.example/"

    def headers(self):
        return {
            "Authorization": "Bearer " + "x" * 40,
            "x-connector-id": "connector-test",
            "User-Agent": "MessageCenterDevice/1.0",
            "Accept": "application/json",
        }


class FakeResponse:
    def __init__(self, url, body=b'{"ok":true}'):
        self.url = url
        self.body = body
        self.read_limit = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return self.url

    def read(self, limit):
        self.read_limit = limit
        return self.body[:limit]


class FakeOpener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        outcome.url = request.full_url
        return outcome


class ConversationProfileTests(unittest.TestCase):
    def request_with(self, profiles, outcomes=None):
        opener = FakeOpener(outcomes or [FakeResponse("") for _ in profiles])
        with patch.object(profiles_module.urllib.request, "build_opener", return_value=opener) as build:
            result = profiles_module.sync_profiles(FakeRelay(), profiles)
        build.assert_called_once()
        self.assertIsInstance(build.call_args.args[0], profiles_module.NoRedirect)
        return result, opener

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
        result, opener = self.request_with([profile])
        self.assertEqual(result, 1)
        request = opener.requests[0]
        self.assertEqual(request.full_url, "https://worker.example/api/connectors/conversation-profiles/group:fixture-1")
        self.assertEqual(request.get_method(), "PUT")
        self.assertEqual(request.data, b"")
        self.assertEqual(request.get_header("Content-length"), "0")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + "x" * 40)
        self.assertEqual(request.get_header("X-connector-id"), "connector-test")
        self.assertEqual(request.get_header("User-agent"), "MessageCenterDevice/1.0")
        self.assertEqual(urllib.parse.unquote(request.get_header("X-conversation-display-name")), "群聊 Café")
        self.assertEqual(urllib.parse.unquote(request.get_header("X-conversation-channel-label")), "即时 消息")
        self.assertEqual(urllib.parse.unquote(request.get_header("X-conversation-last-preview")), "最新消息 🌱")
        self.assertEqual(request.get_header("X-conversation-type"), "group")
        self.assertEqual(request.get_header("X-conversation-placement"), "folded")
        self.assertEqual(request.get_header("X-conversation-pinned"), "1")
        self.assertEqual(request.get_header("X-conversation-unread-count"), "17")
        self.assertEqual(request.get_header("X-conversation-unread-observed-at"), "2026-10-07T12:00:00.000Z")
        self.assertEqual(request.get_header("X-conversation-last-at"), "2026-10-07T12:01:00.000Z")
        self.assertEqual(opener.timeouts, [20])

    def test_empty_batch_does_not_open_network(self):
        with patch.object(profiles_module.urllib.request, "build_opener") as build:
            self.assertEqual(profiles_module.sync_profiles(FakeRelay(), []), 0)
        build.assert_not_called()

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
            with self.subTest(profiles=profiles[:1]), patch.object(
                profiles_module.urllib.request, "build_opener"
            ) as build:
                with self.assertRaises(profiles_module.ProfileSyncError):
                    profiles_module.sync_profiles(FakeRelay(), profiles)
                build.assert_not_called()

    def test_redirect_and_oversized_response_are_rejected(self):
        handler = profiles_module.NoRedirect()
        with self.assertRaises(urllib.error.HTTPError):
            handler.redirect_request(urllib.request.Request("https://worker.example/"), None,
                                     307, "redirect", {}, "https://other.example/")

        oversized = FakeResponse("", b"{}" + b"x" * profiles_module.MAX_RESPONSE)
        with patch.object(profiles_module.urllib.request, "build_opener", return_value=FakeOpener([oversized])):
            with self.assertRaisesRegex(profiles_module.ProfileSyncError, "profile_response_too_large"):
                profiles_module.sync_profiles(FakeRelay(), [
                    {"conversationExternalId": "group-1", "displayName": "Group"}
                ])
        self.assertEqual(oversized.read_limit, profiles_module.MAX_RESPONSE + 1)

    def test_http_or_response_failure_propagates_and_stops_batch(self):
        opener = FakeOpener([
            FakeResponse("", b'{"ok":true}'),
            urllib.error.URLError("offline"),
            FakeResponse(""),
        ])
        with patch.object(profiles_module.urllib.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(profiles_module.ProfileSyncError, "profile_request_failed"):
                profiles_module.sync_profiles(FakeRelay(), [
                    {"conversationExternalId": "group-1", "displayName": "Group 1"},
                    {"conversationExternalId": "group-2", "displayName": "Group 2"},
                    {"conversationExternalId": "group-3", "displayName": "Group 3"},
                ])
        self.assertEqual(len(opener.requests), 2)

    def test_worker_rejection_is_not_acknowledged_as_success(self):
        rejected = FakeResponse("", json.dumps({"ok": False, "error": "invalid_conversation_profile"}).encode())
        with patch.object(profiles_module.urllib.request, "build_opener", return_value=FakeOpener([rejected])):
            with self.assertRaisesRegex(profiles_module.ProfileSyncError, "profile_update_rejected"):
                profiles_module.sync_profiles(FakeRelay(), [
                    {"conversationExternalId": "group-1", "displayName": "Group"}
                ])

    def test_valid_png_avatar_puts_raw_bytes_with_worker_headers(self):
        avatar = b"\x89PNG\r\n\x1a\nsynthetic-png"
        profile = {
            "conversationExternalId": "group-1",
            "displayName": "Group",
            "avatarBase64": base64.b64encode(avatar).decode("ascii"),
        }
        result, opener = self.request_with([profile])
        request = opener.requests[0]
        self.assertEqual(result, 1)
        self.assertEqual(request.data, avatar)
        self.assertEqual(request.get_header("Content-type"), "image/png")
        self.assertEqual(request.get_header("Content-length"), str(len(avatar)))
        self.assertEqual(request.get_header("X-content-sha256"), hashlib.sha256(avatar).hexdigest())

    def test_missing_and_empty_avatar_keep_metadata_only_put(self):
        profiles = [
            {"conversationExternalId": "group-1", "displayName": "Group 1"},
            {"conversationExternalId": "group-2", "displayName": "Group 2", "avatarBase64": ""},
        ]
        result, opener = self.request_with(profiles)
        self.assertEqual(result, 2)
        for request in opener.requests:
            self.assertEqual(request.data, b"")
            self.assertEqual(request.get_header("Content-length"), "0")
            self.assertIsNone(request.get_header("Content-type"))
            self.assertIsNone(request.get_header("X-content-sha256"))

    def test_avatar_base64_is_strict_and_full_batch_is_prevalidated(self):
        avatar = b"\x89PNG\r\n\x1a\nsynthetic-png"
        profiles = [
            {"conversationExternalId": "group-1", "displayName": "Group 1",
             "avatarBase64": base64.b64encode(avatar).decode("ascii")},
            {"conversationExternalId": "group-2", "displayName": "Group 2", "avatarBase64": "%%%="},
        ]
        with patch.object(profiles_module.urllib.request, "build_opener") as build:
            with self.assertRaisesRegex(profiles_module.ProfileSyncError, "invalid_profile_avatar"):
                profiles_module.sync_profiles(FakeRelay(), profiles)
            build.assert_not_called()

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
            with self.subTest(count=len(profiles)), patch.object(
                profiles_module.urllib.request, "build_opener"
            ) as build:
                with self.assertRaisesRegex(profiles_module.ProfileSyncError, "profile_avatar_too_large"):
                    profiles_module.sync_profiles(FakeRelay(), profiles)
                build.assert_not_called()

    def test_invalid_avatar_magic_is_rejected_before_network(self):
        profile = {
            "conversationExternalId": "group-1", "displayName": "Group",
            "avatarBase64": base64.b64encode(b"not-an-image").decode("ascii"),
        }
        with patch.object(profiles_module.urllib.request, "build_opener") as build:
            with self.assertRaisesRegex(profiles_module.ProfileSyncError, "invalid_profile_avatar"):
                profiles_module.sync_profiles(FakeRelay(), [profile])
            build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
