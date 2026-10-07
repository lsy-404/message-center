"""Bounded HTTPS synchronization for conversation profile metadata."""

import datetime
import json
import re
import urllib.error
import urllib.parse
import urllib.request


MAX_PROFILES = 20
MAX_RESPONSE = 1024 * 1024
REQUEST_TIMEOUT = 20
CONVERSATION_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{0,199}\Z")
CONVERSATION_TYPES = {"direct", "group", "unknown"}
PLACEMENTS = {"normal", "folded", "message_box", "unknown"}


class ProfileSyncError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise urllib.error.HTTPError(request.full_url, code, "redirect_refused", headers, response)


def _utf16_length(value):
    try:
        return len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError as exc:
        raise ProfileSyncError("invalid_profile_text") from exc


def _optional_text(profile, key, maximum):
    value = profile.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProfileSyncError("invalid_profile_metadata")
    value = value.strip()
    if _utf16_length(value) > maximum:
        raise ProfileSyncError("invalid_profile_metadata")
    return value


def _timestamp(value):
    if not isinstance(value, str) or not value:
        raise ProfileSyncError("invalid_profile_timestamp")
    try:
        parsed = datetime.datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ProfileSyncError("invalid_profile_timestamp") from exc
    if parsed.tzinfo is None:
        raise ProfileSyncError("invalid_profile_timestamp")
    return parsed.astimezone(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _prepare_profile(profile):
    if not isinstance(profile, dict):
        raise ProfileSyncError("invalid_profile_metadata")
    conversation_id = profile.get("conversationExternalId")
    if not isinstance(conversation_id, str) or not CONVERSATION_ID.fullmatch(conversation_id):
        raise ProfileSyncError("invalid_conversation_id")

    display_name = _optional_text(profile, "displayName", 200)
    if not display_name:
        raise ProfileSyncError("invalid_profile_display_name")

    headers = {
        "x-conversation-display-name": urllib.parse.quote(display_name, safe=""),
    }
    channel_label = _optional_text(profile, "channelLabel", 80)
    if channel_label is not None:
        headers["x-conversation-channel-label"] = urllib.parse.quote(channel_label, safe="")

    conversation_type = profile.get("conversationType")
    if conversation_type is not None:
        if not isinstance(conversation_type, str) or conversation_type not in CONVERSATION_TYPES:
            raise ProfileSyncError("invalid_profile_metadata")
        headers["x-conversation-type"] = conversation_type

    placement = profile.get("placement")
    if placement is not None:
        if not isinstance(placement, str) or placement not in PLACEMENTS:
            raise ProfileSyncError("invalid_profile_metadata")
        headers["x-conversation-placement"] = placement

    pinned = profile.get("pinned")
    if pinned is not None:
        if not isinstance(pinned, bool):
            raise ProfileSyncError("invalid_profile_metadata")
        headers["x-conversation-pinned"] = "1" if pinned else "0"

    unread_count = profile.get("unreadCount")
    if unread_count is not None:
        if isinstance(unread_count, bool) or not isinstance(unread_count, int) or not 0 <= unread_count <= 9_999_999:
            raise ProfileSyncError("invalid_profile_metadata")
        headers["x-conversation-unread-count"] = str(unread_count)

    unread_observed_at = profile.get("unreadObservedAt")
    if unread_observed_at is not None:
        if unread_count is None:
            raise ProfileSyncError("invalid_profile_metadata")
        headers["x-conversation-unread-observed-at"] = _timestamp(unread_observed_at)

    last_preview = _optional_text(profile, "lastMessagePreview", 500)
    if last_preview is not None:
        headers["x-conversation-last-preview"] = urllib.parse.quote(last_preview, safe="")

    last_message_at = profile.get("lastMessageAt")
    if last_message_at is not None:
        headers["x-conversation-last-at"] = _timestamp(last_message_at)

    return conversation_id, headers


def sync_profiles(relay, profiles):
    """PUT up to twenty profiles; any failure propagates to the scan caller."""
    if not isinstance(profiles, list) or len(profiles) > MAX_PROFILES:
        raise ProfileSyncError("invalid_profile_batch")
    prepared = [_prepare_profile(profile) for profile in profiles]
    if not prepared:
        return 0

    opener = urllib.request.build_opener(NoRedirect())
    base = relay.base.rstrip("/")
    headers_base = relay.headers()
    for conversation_id, profile_headers in prepared:
        headers = dict(headers_base)
        headers.update(profile_headers)
        headers["Content-Length"] = "0"
        request = urllib.request.Request(
            base + "/api/connectors/conversation-profiles/" + conversation_id,
            data=b"",
            headers=headers,
            method="PUT",
        )
        try:
            with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
                if response.geturl() != request.full_url:
                    raise ProfileSyncError("profile_redirect_refused")
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise ProfileSyncError("profile_response_too_large")
        except ProfileSyncError:
            raise
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise ProfileSyncError("profile_request_failed") from exc

        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProfileSyncError("profile_invalid_response") from exc
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise ProfileSyncError("profile_update_rejected")
    return len(prepared)
