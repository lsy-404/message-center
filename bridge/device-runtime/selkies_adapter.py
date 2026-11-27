#!/usr/bin/env python3
"""Device adapter for WeChat and QQ desktop clients running in a wechat-selkies container.

The runtime runs this executable once per request with one JSON object on stdin. Each profile names a container in
``selkies_adapter.json`` beside this file and a file holding the container's Selkies master token. A scan reads the
client's chat list through the container's Pelorus accessibility API and reports every chat whose last message changed.
Chats are never opened, so nothing is marked read.
Sending is refused, so the connector must be configured ``receiveOnly``.
"""

import base64
import datetime
import hashlib
import json
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.request

REQUEST_TIMEOUT = 15
MAX_REMEMBERED = 300
MAX_PROFILES = 20
MAX_BODY = 20000
CONFIG_PATH = os.path.splitext(os.path.abspath(__file__))[0] + ".json"

APPS = {
    "wechat": {"app_id": "wechat", "sign_in": ("扫码登录", "当前登录用户")},
    "qq": {"app_id": "QQ", "sign_in": ("手机QQ扫码登录",)},
}
# Rows that gather other chats rather than being one conversation.
AGGREGATES = {
    "wechat": {"公众号", "折叠的聊天", "服务号", "订阅号"},
    "qq": {"群助手", "服务号", "订阅号"},
}
WECHAT_PINNED = "已置顶"
WECHAT_MUTED = "消息免打扰"
WECHAT_UNREAD = re.compile(r"^\[(\d+)条\]\s*")
QQ_UNREAD = re.compile(r"^(\d+)条未读$")
QQ_MUTED = "免打扰"
TIME_LABEL = re.compile(r"^(\d{1,4}[:/]\d{1,2}(/\d{1,2})?|昨天|前天|星期.)")
# Row-level markers the client prints in front of a preview; they describe the row, not the message.
ROW_MARKERS = re.compile(r"^(\[(有人@我|有新文件|有人@你|草稿)\])+")
SENDER = re.compile(r"^([^:：\[\]\n]{1,64})(?:: |：)(.*)$", re.S)


class AdapterError(Exception):
    pass


def digest(value):
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode("utf-8")).digest()).decode("ascii")[:16].replace("-", "x").replace("_", "y")


def iso(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_config():
    try:
        info = os.stat(CONFIG_PATH)
    except OSError:
        raise AdapterError("config_missing")
    if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
        raise AdapterError("config_permissions")
    with open(CONFIG_PATH, encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict) or not isinstance(config.get("profiles"), dict):
        raise AdapterError("config_invalid")
    return config


def container(config, profile):
    entry = config["profiles"].get(profile)
    if not isinstance(entry, dict) or not isinstance(entry.get("desktopUrl"), str):
        raise AdapterError("profile_unknown")
    url = entry["desktopUrl"].rstrip("/")
    if not re.match(r"^https?://", url):
        raise AdapterError("profile_invalid")
    token_file = os.path.expanduser(str(entry.get("tokenFile", "")))
    try:
        with open(token_file, encoding="utf-8") as handle:
            token = handle.read().strip()
    except OSError:
        raise AdapterError("token_missing")
    if not token:
        raise AdapterError("token_missing")
    return url, "Bearer " + token


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise urllib.error.HTTPError(request.full_url, code, "redirect_refused", headers, response)


def pelorus(url, authorization, path, method="GET"):
    request = urllib.request.Request(url + "/api/pelorus" + path, method=method, data=b"" if method == "POST" else None,
                                     headers={"Authorization": authorization, "Accept": "application/json"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=REQUEST_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise AdapterError("desktop_auth_refused" if error.code in (401, 403) else "desktop_http_{}".format(error.code))
    except (urllib.error.URLError, OSError, ValueError):
        raise AdapterError("desktop_unreachable")


def walk(node):
    yield node
    for child in node.get("children") or []:
        yield from walk(child)


def text_of(node):
    return (node.get("name") or node.get("text") or "").strip()


def wechat_rows(tree):
    """WeChat names each 会话 row ``name\\n[已置顶\\n]preview\\ntime\\n[消息免打扰\\n]``; muted and folded chats add ``[n条]``."""
    chats = next((node for node in walk(tree) if node.get("role") == "list" and node.get("name") == "会话"), None)
    if chats is None:
        return None
    rows = []
    for item in chats.get("children") or []:
        if item.get("role") != "list item":
            continue
        lines = (item.get("name") or item.get("text") or "").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        pinned = any(line.strip() == WECHAT_PINNED for line in lines)
        muted = any(line.strip() == WECHAT_MUTED for line in lines)
        lines = [line for line in lines if line.strip() not in (WECHAT_PINNED, WECHAT_MUTED)]
        if not lines or not lines[0].strip():
            continue
        name = lines.pop(0).strip()
        label = lines.pop().strip() if len(lines) >= 2 else ""
        body = [line.strip() for line in lines if line.strip()]
        unread = None
        match = WECHAT_UNREAD.match(body[0]) if body else None
        if match:
            unread = int(match.group(1))
            body[0] = body[0][match.end():]
        rows.append({"name": name, "preview": " ".join(part for part in body if part).strip(), "time": label,
                     "unread": unread, "pinned": pinned, "muted": muted})
    return rows


def qq_rows(tree):
    """QQ draws each 会话列表 row as a panel of text pieces: name, time, then the preview split into pieces."""
    chats = next((node for node in walk(tree) if node.get("name") == "会话列表"), None)
    if chats is None:
        return None
    rows = []
    for item in chats.get("children") or []:
        texts = []
        state = {"unread": 0, "muted": False}

        def visit(node):
            match = QQ_UNREAD.match(node.get("name") or "")
            if match:
                state["unread"] = int(match.group(1))
                return
            if node.get("name") == QQ_MUTED and node.get("role") != "static":
                state["muted"] = True
                return
            if node.get("role") == "static" and text_of(node):
                texts.append(text_of(node))
            for child in node.get("children") or []:
                visit(child)

        visit(item)
        if not texts:
            continue
        name = texts.pop(0)
        label = texts.pop(0) if texts and TIME_LABEL.match(texts[0]) else ""
        rows.append({"name": name, "preview": "".join(texts).strip(), "time": label,
                     "unread": state["unread"], "pinned": False, "muted": state["muted"]})
    return rows


def qq_owner(tree):
    for node in walk(tree):
        name = node.get("name") or ""
        if node.get("role") == "button" and name.endswith("的头像"):
            return name[:-len("的头像")]
    return None


PARSERS = {"wechat": wechat_rows, "qq": qq_rows}


def read_rows(driver, url, authorization):
    app = APPS[driver]
    desktop = pelorus(url, authorization, "/desktop")
    windows = [window for window in desktop.get("windows") or []
               if window.get("app_id") == app["app_id"] and window.get("type") == "normal" and window.get("mapped")]
    if not windows:
        raise AdapterError("client_not_running")
    windows.sort(key=lambda window: -(window["rect"][2] * window["rect"][3]))
    for window in windows:
        window_id = int(window["id"])
        tree = pelorus(url, authorization, "/window/{}/tree".format(window_id)).get("tree") or {}
        if any(text_of(node).startswith(app["sign_in"]) for node in walk(tree)):
            raise AdapterError("client_signed_out")
        rows = PARSERS[driver](tree)
        if rows is None:
            continue
        # Only rows on screen are in the tree, so a maximized window exposes the most chats.
        if window.get("minimized") or not window.get("maximized"):
            if window.get("minimized"):
                pelorus(url, authorization, "/window/{}/restore".format(window_id), "POST")
            pelorus(url, authorization, "/window/{}/maximize".format(window_id), "POST")
            tree = pelorus(url, authorization, "/window/{}/tree".format(window_id)).get("tree") or {}
            rows = PARSERS[driver](tree) or rows
        return rows, (qq_owner(tree) if driver == "qq" else None)
    raise AdapterError("chat_list_hidden")


def split_preview(preview):
    """The row markers, the sender a group preview names, and the message text."""
    markers = ROW_MARKERS.match(preview)
    marker_text = markers.group(0) if markers else ""
    rest = preview[len(marker_text):]
    sender = SENDER.match(rest)
    if sender:
        return marker_text, sender.group(1).strip(), sender.group(2).strip()
    return marker_text, None, rest.strip()


def scan(request, config):
    driver = request.get("driver")
    if driver not in APPS:
        raise AdapterError("driver_unsupported")
    url, authorization = container(config, request.get("profile"))
    rows, owner = read_rows(driver, url, authorization)
    cursor = request.get("cursor") if isinstance(request.get("cursor"), dict) else {}
    seen = dict(cursor.get("chats") or {})
    first = not seen
    limit = max(1, min(int(request.get("limit") or 20), 20))
    now = int(time.time() * 1000)
    prefix = "wx" if driver == "wechat" else "qq"
    messages, profiles, more = [], [], False
    for row in rows:
        if row["name"] in AGGREGATES[driver] or not row["preview"]:
            continue
        conversation = "{}-{}".format(prefix, digest(row["name"]))
        markers, sender, body = split_preview(row["preview"])
        previous = seen.get(conversation)
        group = bool(sender) or bool(previous and previous.get("g"))
        fingerprint = digest(row["preview"])
        unread = row["unread"] if isinstance(row["unread"], int) else 0
        changed = previous is None or previous.get("p") != fingerprint or unread > previous.get("u", 0)
        if not changed:
            continue
        if len(messages) >= limit:
            more = True
            continue
        if not first or previous is None:
            message = {
                "externalId": "{}:{}:{}".format(conversation, fingerprint, now),
                "conversationExternalId": conversation,
                "conversationTitle": row["name"][:200],
                "senderName": (sender if group and sender else row["name"])[:200],
                "occurredAt": iso(now),
                "observedAt": iso(now),
                "body": (body or row["preview"])[:MAX_BODY],
                "conversationType": "group" if group else "direct",
                "trigger": ("mention" if "@" in markers else "background") if group else "direct",
            }
            if group and owner and sender == owner:
                message["isSelf"] = True
            messages.append(message)
        profile = {"conversationExternalId": conversation, "displayName": row["name"][:200],
                   "conversationType": "group" if group else ("direct" if sender is None and previous and previous.get("d") else "unknown"),
                   "placement": "normal", "pinned": bool(row["pinned"]),
                   "lastMessagePreview": row["preview"][:500], "lastMessageAt": iso(now)}
        if isinstance(row["unread"], int):
            profile["unreadCount"] = row["unread"]
            profile["unreadObservedAt"] = iso(now)
        if len(profiles) < MAX_PROFILES:
            profiles.append(profile)
        seen[conversation] = {"p": fingerprint, "u": unread, "g": group, "at": now}
    kept = sorted(seen.items(), key=lambda item: -item[1].get("at", 0))[:MAX_REMEMBERED]
    return {"ok": True, "sourceReadStatus": "complete", "health": "online", "cursor": {"chats": dict(kept)},
            "messages": messages, "conversationProfiles": profiles, "active": True, "more": more}


def handle(request):
    operation = request.get("op") if isinstance(request, dict) else None
    if operation == "send":
        return {"ok": False, "dispatched": False, "error": "send_unsupported"}
    if operation != "scan":
        return {"ok": False, "error": "operation_unsupported"}
    try:
        return scan(request, load_config())
    except AdapterError as error:
        print(str(error), file=sys.stderr)
        return {"ok": False, "sourceReadStatus": "failed", "error": str(error)}


def main():
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sys.stdout.write(json.dumps(handle(request), ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
