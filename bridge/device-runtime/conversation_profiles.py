"""Bounded HTTPS synchronization for conversation profile metadata."""

import base64
import datetime
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request


MAX_PROFILES = 20
MAX_AVATAR_BYTES = 128 * 1024
MAX_AVATAR_BATCH_BYTES = 128 * 1024
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


def _decode_avatar(profile, remaining_bytes):
    if "avatarBase64" not in profile:
        return None, None
    encoded = profile["avatarBase64"]
    if not isinstance(encoded, str):
        raise ProfileSyncError("invalid_profile_avatar")
    if encoded == "":
        return None, None
    encoded_limit = 4 * ((min(MAX_AVATAR_BYTES, remaining_bytes) + 2) // 3)
    if not remaining_bytes or len(encoded) > encoded_limit:
        raise ProfileSyncError("profile_avatar_too_large")
    try:
        encoded_bytes = encoded.encode("ascii")
        avatar = base64.b64decode(encoded_bytes, validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ProfileSyncError("invalid_profile_avatar") from exc
    if (not avatar or len(avatar) > MAX_AVATAR_BYTES or len(avatar) > remaining_bytes or
            base64.b64encode(avatar).decode("ascii") != encoded):
        if avatar and (len(avatar) > MAX_AVATAR_BYTES or len(avatar) > remaining_bytes):
            raise ProfileSyncError("profile_avatar_too_large")
        raise ProfileSyncError("invalid_profile_avatar")

    if avatar.startswith(b"\x89PNG\r\n\x1a\n"):
        content_type = "image/png"
    elif avatar.startswith(b"\xff\xd8\xff"):
        content_type = "image/jpeg"
    elif avatar.startswith((b"GIF87a", b"GIF89a")):
        content_type = "image/gif"
    elif len(avatar) >= 12 and avatar[:4] == b"RIFF" and avatar[8:12] == b"WEBP":
        content_type = "image/webp"
    else:
        raise ProfileSyncError("invalid_profile_avatar")
    return avatar, content_type


def _prepare_profile(profile, remaining_avatar_bytes=MAX_AVATAR_BATCH_BYTES):
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

    avatar, content_type = _decode_avatar(profile, remaining_avatar_bytes)
    return conversation_id, headers, avatar, content_type


def sync_profiles(relay, profiles):
    """PUT up to twenty profiles; any failure propagates to the scan caller."""
    if not isinstance(profiles, list) or len(profiles) > MAX_PROFILES:
        raise ProfileSyncError("invalid_profile_batch")
    prepared = []
    remaining_avatar_bytes = MAX_AVATAR_BATCH_BYTES
    for profile in profiles:
        item = _prepare_profile(profile, remaining_avatar_bytes)
        if item[2] is not None:
            remaining_avatar_bytes -= len(item[2])
        prepared.append(item)
    if not prepared:
        return 0

    opener = urllib.request.build_opener(NoRedirect())
    base = relay.base.rstrip("/")
    headers_base = relay.headers()
    for conversation_id, profile_headers, avatar, content_type in prepared:
        headers = dict(headers_base)
        headers.update(profile_headers)
        body = avatar if avatar is not None else b""
        headers["Content-Length"] = str(len(body))
        if avatar is not None:
            headers["Content-Type"] = content_type
            headers["x-content-sha256"] = hashlib.sha256(avatar).hexdigest()
        request = urllib.request.Request(
            base + "/api/connectors/conversation-profiles/" + conversation_id,
            data=body,
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


def sync_sender_avatars(relay, avatars):
    """PUT bounded sender images; callers commit their source cursor only on success."""
    if not isinstance(avatars, list) or len(avatars) > MAX_PROFILES:
        raise ProfileSyncError("invalid_sender_avatar_batch")
    prepared = []
    remaining_avatar_bytes = MAX_AVATAR_BATCH_BYTES
    for item in avatars:
        if not isinstance(item, dict):
            raise ProfileSyncError("invalid_sender_avatar")
        sender_id = item.get("senderId")
        if not isinstance(sender_id, str) or not CONVERSATION_ID.fullmatch(sender_id):
            raise ProfileSyncError("invalid_sender_id")
        avatar, content_type = _decode_avatar(item, remaining_avatar_bytes)
        if avatar is not None:
            remaining_avatar_bytes -= len(avatar)
            prepared.append((sender_id, avatar, content_type))
    if not prepared:
        return 0

    opener = urllib.request.build_opener(NoRedirect())
    base = relay.base.rstrip("/")
    headers_base = relay.headers()
    for sender_id, avatar, content_type in prepared:
        headers = dict(headers_base)
        headers["Content-Length"] = str(len(avatar))
        headers["Content-Type"] = content_type
        headers["x-content-sha256"] = hashlib.sha256(avatar).hexdigest()
        request = urllib.request.Request(
            base + "/api/connectors/sender-avatars/" + sender_id,
            data=avatar,
            headers=headers,
            method="PUT",
        )
        try:
            with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
                if response.geturl() != request.full_url:
                    raise ProfileSyncError("sender_avatar_redirect_refused")
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise ProfileSyncError("sender_avatar_response_too_large")
        except ProfileSyncError:
            raise
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise ProfileSyncError("sender_avatar_request_failed") from exc

        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProfileSyncError("sender_avatar_invalid_response") from exc
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise ProfileSyncError("sender_avatar_update_rejected")
    return len(prepared)
