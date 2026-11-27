#!/usr/bin/env python3
"""Device adapter for WeChat and QQ desktop clients running in a wechat-selkies container.

The runtime runs this executable once per request with one JSON object on stdin. Each profile names a container in
``selkies_adapter.json`` beside this file and a file holding the container's Selkies master token. A scan reads the
client's chat list, and the chats folded into 群助手 / 折叠的聊天, through the container's Pelorus accessibility API and
reports every chat whose last message changed. Scans never open a chat, so nothing is marked read. A send opens the
chat, types the text, sends it and checks the message list before it reports a receipt.
"""

import base64
import datetime
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.request

REQUEST_TIMEOUT = 15
MAX_REMEMBERED = 300
MAX_PROFILES = 20
MAX_BODY = 20000
MAX_STATE_CONVERSATIONS = 1000
FOLDER_REFRESH_MS = 10 * 60 * 1000
RECENT_SEND_MS = 15 * 60 * 1000
SCROLL_PAGES = 8
CONFIG_PATH = os.path.splitext(os.path.abspath(__file__))[0] + ".json"
STATE_PATH = os.path.splitext(os.path.abspath(__file__))[0] + ".state.json"

APPS = {
    "wechat": {"app_id": "wechat", "sign_in": ("扫码登录", "当前登录用户"), "folder": "折叠的聊天", "prefix": "wx"},
    "qq": {"app_id": "QQ", "sign_in": ("手机QQ扫码登录",), "folder": "群助手", "prefix": "qq"},
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
QQ_MEMBER_COUNT = re.compile(r"\s*\(\d+人\)$")
TIME_LABEL = re.compile(r"^(\d{1,4}[:/]\d{1,2}(/\d{1,2})?|昨天|前天|星期.)")
# Row-level markers the client prints in front of a preview; they describe the row, not the message.
ROW_MARKERS = re.compile(r"^(\[(有人@我|有新文件|有人@你|草稿)\])+")
SENDER = re.compile(r"^([^:：\[\]\n]{1,64})(?:: |：)(.*)$", re.S)


class AdapterError(Exception):
    pass


def digest(value):
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode("utf-8")).digest()).decode("ascii")[:16].replace("-", "x").replace("_", "y")


def collapse(value):
    return re.sub(r"\s+", "", value or "")


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


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    state.setdefault("conversations", {})
    state.setdefault("recent", {})
    return state


def save_state(state):
    conversations = state["conversations"]
    if len(conversations) > MAX_STATE_CONVERSATIONS:
        kept = sorted(conversations.items(), key=lambda item: -item[1].get("at", 0))[:MAX_STATE_CONVERSATIONS]
        state["conversations"] = dict(kept)
    now = int(time.time() * 1000)
    state["recent"] = {key: [entry for entry in entries if now - entry.get("at", 0) < RECENT_SEND_MS]
                       for key, entries in state["recent"].items()}
    state["recent"] = {key: entries for key, entries in state["recent"].items() if entries}
    directory = os.path.dirname(STATE_PATH)
    descriptor, temporary = tempfile.mkstemp(prefix=".selkies-state-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, separators=(",", ":"))
        os.chmod(temporary, 0o600)
        os.replace(temporary, STATE_PATH)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


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
    return Desktop(url, "Bearer " + token), entry


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise urllib.error.HTTPError(request.full_url, code, "redirect_refused", headers, response)


class Desktop:
    """The container's Pelorus API: window list, accessibility trees and input actions."""

    def __init__(self, url, authorization):
        self.url = url
        self.authorization = authorization

    def call(self, path, method="GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        if method == "POST" and data is None:
            data = b""
        headers = {"Authorization": self.authorization, "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.url + "/api/pelorus" + path, method=method, data=data, headers=headers)
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=REQUEST_TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise AdapterError("desktop_auth_refused" if error.code in (401, 403) else "desktop_http_{}".format(error.code))
        except (urllib.error.URLError, OSError, ValueError):
            raise AdapterError("desktop_unreachable")

    def tree(self, window_id):
        return self.call("/window/{}/tree".format(window_id)).get("tree") or {}

    def tool(self, name, **arguments):
        result = self.call("/tool", "POST", {"name": name, "arguments": arguments})
        if result.get("failed"):
            raise AdapterError("desktop_action_failed")
        return result.get("text") or ""

    def ref(self, window_id, pattern):
        """The `look` reference of the first control whose outline line matches `pattern`."""
        match = re.search(r"\[(e\d+)\] " + pattern, self.tool("look", window=window_id))
        return match.group(1) if match else None

    def click(self, bounds):
        self.tool("click", at=[int(bounds["x"] + bounds["w"] / 2), int(bounds["y"] + bounds["h"] / 2)])

    def activate(self, window_id):
        # Clicks and scrolls land on whatever window is on top at that point, so raise the target first.
        self.call("/window/{}/activate".format(window_id), "POST")
        time.sleep(0.3)


def walk(node):
    yield node
    for child in node.get("children") or []:
        yield from walk(child)


def text_of(node):
    return (node.get("name") or node.get("text") or "").strip()


def find(tree, predicate):
    return next((node for node in walk(tree) if predicate(node)), None)


def wechat_list_rows(chats, placement):
    """WeChat names each row ``name\\n[已置顶\\n]preview\\ntime\\n[消息免打扰\\n]``; muted and folded chats add ``[n条]``."""
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
                     "unread": unread, "pinned": pinned, "muted": muted, "placement": placement,
                     "bounds": item.get("bounds"), "selected": bool((item.get("states") or {}).get("selected"))})
    return rows


def wechat_open_chat(tree):
    """The open chat's name: its input box is named after it."""
    node = find(tree, lambda n: n.get("role") == "text" and (n.get("states") or {}).get("editable") and n.get("name") not in (None, "", "搜索"))
    return node.get("name") if node else None


def wechat_rows(tree):
    chats = find(tree, lambda n: n.get("role") == "list" and n.get("name") == "会话")
    if chats is None:
        return None
    rows = wechat_list_rows(chats, "normal")
    # The selected row's name is elided in the narrow list; the open chat carries the full name.
    title = wechat_open_chat(tree)
    for row in rows:
        if row["selected"] and title and row["name"] != title and title.startswith(row["name"]):
            row["name"] = title
    return rows


def qq_list_rows(chats, placement):
    """QQ draws each 会话列表 row as a panel: name pieces, then sections for the time, the preview pieces, the unread
    badge (``n条未读``) and the muted mark (``免打扰``). Names with emoji arrive as several pieces."""
    rows = []
    for panel in chats.get("children") or []:
        content = find(panel, lambda n: any(c.get("role") == "static" and text_of(c) for c in n.get("children") or []))
        if content is None:
            continue
        name = "".join(text_of(c) for c in content.get("children") or [] if c.get("role") == "static" and text_of(c))
        label, preview, unread, muted = "", [], 0, False
        for child in content.get("children") or []:
            if child.get("role") == "static":
                continue
            child_name = child.get("name") or ""
            match = QQ_UNREAD.match(child_name)
            if match:
                unread = int(match.group(1))
                continue
            if child_name == QQ_MUTED:
                muted = True
                continue
            texts = [text_of(n) for n in walk(child) if n.get("role") == "static" and text_of(n)]
            if not label and not preview and len(texts) == 1 and TIME_LABEL.match(texts[0]):
                label = texts[0]
                continue
            preview.extend(texts)
        if name:
            rows.append({"name": name, "preview": "".join(preview).strip(), "time": label, "unread": unread,
                         "pinned": False, "muted": muted, "placement": placement, "bounds": panel.get("bounds"), "selected": False})
    return rows


def qq_rows(tree):
    chats = find(tree, lambda n: n.get("name") == "会话列表")
    return None if chats is None else qq_list_rows(chats, "normal")


def qq_owner(tree):
    for node in walk(tree):
        name = node.get("name") or ""
        if node.get("role") == "button" and name.endswith("的头像"):
            return name[:-len("的头像")]
    return None


def in_folder(driver, tree):
    if driver == "wechat":
        return find(tree, lambda n: n.get("role") == "list" and n.get("name") == APPS[driver]["folder"]) is not None
    return find(tree, lambda n: n.get("role") == "static" and n.get("name") == "返回") is not None


def leave_folder(desktop, driver, window_id, tree):
    if driver == "wechat":
        ref = desktop.ref(window_id, r'button "返回"')
        if ref:
            desktop.tool("click", ref=ref)
    else:
        back = find(tree, lambda n: n.get("role") == "static" and n.get("name") == "返回")
        if back and back.get("bounds"):
            desktop.click(back["bounds"])
    time.sleep(1)


def main_rows(driver, tree):
    return wechat_rows(tree) if driver == "wechat" else qq_rows(tree)


def open_client(desktop, driver):
    """The client's main window, signed in, maximized and showing its main chat list."""
    app = APPS[driver]

    def client_windows():
        return [w for w in desktop.call("/desktop").get("windows") or []
                if w.get("app_id") == app["app_id"] and w.get("type") == "normal" and w.get("mapped")]

    windows = client_windows()
    if not windows and restore_from_tray(desktop, driver):
        windows = client_windows()
    if not windows:
        raise AdapterError("client_not_running")
    windows.sort(key=lambda w: -(w["rect"][2] * w["rect"][3]))
    for window in windows:
        window_id = int(window["id"])
        tree = desktop.tree(window_id)
        if any(text_of(node).startswith(app["sign_in"]) for node in walk(tree)):
            raise AdapterError("client_signed_out")
        if main_rows(driver, tree) is None and not in_folder(driver, tree):
            tab = desktop.ref(window_id, r'toggle button "消息"' if driver == "qq" else r'button "(WeChat|微信)"')
            if not tab:
                continue
            desktop.tool("click", ref=tab)
            time.sleep(1)
            tree = desktop.tree(window_id)
            if main_rows(driver, tree) is None:
                continue
        # Only rows on screen are in the tree, so a maximized window exposes the most chats.
        if window.get("minimized"):
            desktop.call("/window/{}/restore".format(window_id), "POST")
        if window.get("minimized") or not window.get("maximized"):
            desktop.call("/window/{}/maximize".format(window_id), "POST")
            tree = desktop.tree(window_id)
        if in_folder(driver, tree):
            leave_folder(desktop, driver, window_id, tree)
            tree = desktop.tree(window_id)
        if main_rows(driver, tree) is not None:
            return window_id, tree
    raise AdapterError("chat_list_hidden")


def wechat_list_center(tree, list_name):
    chats = find(tree, lambda n: n.get("role") == "list" and n.get("name") == list_name)
    bounds = chats.get("bounds") if chats else None
    return [int(bounds["x"] + bounds["w"] / 2), int(bounds["y"] + bounds["h"] / 2)] if bounds else None


def wechat_find_row(desktop, window_id, list_name, name):
    """Scrolls a WeChat chat list from the top until the row named `name` is on screen."""
    tree = desktop.tree(window_id)
    center = wechat_list_center(tree, list_name)
    if not center:
        return None
    desktop.tool("scroll", at=center, direction="up", amount=30)
    previous = None
    for _ in range(SCROLL_PAGES):
        tree = desktop.tree(window_id)
        chats = find(tree, lambda n: n.get("role") == "list" and n.get("name") == list_name)
        rows = wechat_list_rows(chats, "normal") if chats else []
        for row in rows:
            if row["bounds"] and (row["name"] == name or (row["selected"] and name.startswith(row["name"]))):
                return row
        names = [row["name"] for row in rows]
        if names == previous:
            return None
        previous = names
        desktop.tool("scroll", at=center, direction="down", amount=5)
        time.sleep(0.5)
    return None


def stable_click(desktop, window_id, locate):
    """Clicks the row `locate(tree)` returns once two reads 400 ms apart agree on it and on every row above it.

    Chat lists reorder whenever a message arrives, so a row read a moment ago may have moved; clicking a moved row
    would open another chat and mark it read."""
    for _ in range(4):
        first = locate(desktop.tree(window_id))
        time.sleep(0.4)
        second = locate(desktop.tree(window_id))
        if first and second and first[0]["bounds"] == second[0]["bounds"] and first[1] == second[1]:
            desktop.click(second[0]["bounds"])
            return True
    return False


def row_locator(driver, list_name, name, placement="normal"):
    """A locate function for stable_click: the row named `name` and the names of the rows above it."""
    def locate(tree):
        if driver == "wechat":
            chats = find(tree, lambda n: n.get("role") == "list" and n.get("name") == list_name)
            rows = wechat_list_rows(chats, placement) if chats else []
        else:
            chats = find(tree, lambda n: n.get("name") == "会话列表")
            rows = qq_list_rows(chats, placement) if chats else []
        for index, row in enumerate(rows):
            if row["bounds"] and (row["name"] == name or (row["selected"] and name.startswith(row["name"]))):
                return row, [r["name"] for r in rows[:index]]
        return None
    return locate


def wechat_scroll_top(desktop, window_id):
    center = wechat_list_center(desktop.tree(window_id), "会话")
    if center:
        desktop.tool("scroll", at=center, direction="up", amount=30)


def read_folder(desktop, driver, window_id, rows):
    """Opens 群助手 / 折叠的聊天, reads the chats on screen inside it and returns to the main list."""
    folder = APPS[driver]["folder"]
    desktop.activate(window_id)
    row = next((r for r in rows if r["name"] == folder and r["bounds"]), None)
    if row is None and driver == "wechat":
        row = wechat_find_row(desktop, window_id, "会话", folder)
    if row is None or not stable_click(desktop, window_id, row_locator(driver, "会话", folder)):
        return None
    tree = desktop.tree(window_id)
    for _ in range(6):
        time.sleep(0.6)
        tree = desktop.tree(window_id)
        if in_folder(driver, tree):
            break
    if driver == "wechat":
        chats = find(tree, lambda n: n.get("role") == "list" and n.get("name") == folder)
        folded = wechat_list_rows(chats, "folded") if chats else None
    else:
        folded = qq_rows(tree) if in_folder(driver, tree) else None
        if folded is not None:
            folded = [dict(r, placement="folded") for r in folded]
    if in_folder(driver, tree):
        leave_folder(desktop, driver, window_id, tree)
    if driver == "wechat":
        wechat_scroll_top(desktop, window_id)
    return folded


def split_preview(preview):
    """The row markers, the sender a group preview names, and the message text."""
    markers = ROW_MARKERS.match(preview)
    marker_text = markers.group(0) if markers else ""
    rest = preview[len(marker_text):]
    sender = SENDER.match(rest)
    if sender:
        return marker_text, sender.group(1).strip(), sender.group(2).strip()
    return marker_text, None, rest.strip()


def own_echo(state, conversation, texts, now):
    """Whether a preview repeats a message this adapter just sent; consumes the matching record."""
    entries = state["recent"].get(conversation) or []
    wanted = {digest(collapse(text)) for text in texts if text}
    for index, entry in enumerate(entries):
        if now - entry.get("at", 0) < RECENT_SEND_MS and entry.get("t") in wanted:
            del entries[index]
            return True
    return False


def scan(request, config):
    driver = request.get("driver")
    if driver not in APPS:
        raise AdapterError("driver_unsupported")
    desktop, entry = container(config, request.get("profile"))
    state = load_state()
    window_id, tree = open_client(desktop, driver)
    owner = qq_owner(tree) if driver == "qq" else None
    rows = main_rows(driver, tree) or []
    cursor = request.get("cursor") if isinstance(request.get("cursor"), dict) else {}
    seen = dict(cursor.get("chats") or {})
    folder_state = dict(cursor.get("folder") or {})
    limit = max(1, min(int(request.get("limit") or 20), 20))
    now = int(time.time() * 1000)

    aggregate = next((r for r in rows if r["name"] == APPS[driver]["folder"]), None)
    aggregate_print = digest("{}\n{}".format(aggregate["preview"], aggregate["unread"])) if aggregate else None
    due = (aggregate_print and folder_state.get("p") != aggregate_print) or now - folder_state.get("at", 0) >= FOLDER_REFRESH_MS
    if entry.get("readFolders") is True and due:
        folded = read_folder(desktop, driver, window_id, rows)
        if folded is not None:
            rows = rows + folded
            folder_state = {"p": aggregate_print or folder_state.get("p"), "at": now}

    prefix = APPS[driver]["prefix"]
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
        state["conversations"][conversation] = {"name": row["name"], "folder": row["placement"] == "folded", "at": now}
        changed = previous is None or previous.get("p") != fingerprint or unread > previous.get("u", 0)
        if not changed:
            continue
        if len(messages) >= limit:
            more = True
            continue
        if not own_echo(state, conversation, [row["preview"], body], now):
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
                "placement": row["placement"],
            }
            if group and owner and sender == owner:
                message["isSelf"] = True
            messages.append(message)
        profile = {"conversationExternalId": conversation, "displayName": row["name"][:200],
                   "conversationType": "group" if group else "direct", "placement": row["placement"],
                   "pinned": bool(row["pinned"]), "muted": bool(row["muted"]),
                   "lastMessagePreview": row["preview"][:500], "lastMessageAt": iso(now)}
        if isinstance(row["unread"], int):
            profile["unreadCount"] = row["unread"]
            profile["unreadObservedAt"] = iso(now)
        if len(profiles) < MAX_PROFILES:
            profiles.append(profile)
        seen[conversation] = {"p": fingerprint, "u": unread, "g": group, "at": now}
    save_state(state)
    kept = sorted(seen.items(), key=lambda item: -item[1].get("at", 0))[:MAX_REMEMBERED]
    return {"ok": True, "sourceReadStatus": "complete", "health": "online",
            "cursor": {"chats": dict(kept), "folder": folder_state},
            "messages": messages, "conversationProfiles": profiles, "active": True, "more": more}


def chat_input(driver, tree, name, loose=False):
    """The open chat's input when the open chat is `name`: (node, current text). `loose` also accepts an input named
    with `name` as a prefix, for a row the list shows with a shorter name than the chat (文件传输 / 文件传输助手);
    it is only used right after clicking that exact row."""
    def named(node_name):
        return node_name == name or (loose and isinstance(node_name, str) and node_name.startswith(name))
    if driver == "wechat":
        node = find(tree, lambda n: n.get("role") == "text" and (n.get("states") or {}).get("editable")
                    and n.get("name") != "搜索" and named(n.get("name")))
        return (node, (node.get("text") or "") if node else "")
    node = find(tree, lambda n: n.get("role") == "section" and (n.get("states") or {}).get("editable") and named(n.get("name")))
    if node is None:
        titled = find(tree, lambda n: n.get("role") == "button" and named(n.get("name")) and (n.get("bounds") or {}).get("x", 0) > 300)
        editable = [n for n in walk(tree) if n.get("role") == "section" and (n.get("states") or {}).get("editable")]
        node = editable[0] if titled and len(editable) == 1 else None
    if node is None:
        return None, ""
    return node, "\n".join(text_of(n) for n in walk(node) if n is not node and n.get("role") == "static" and text_of(n))


def last_message(driver, tree):
    if driver == "wechat":
        messages = find(tree, lambda n: n.get("role") == "list" and n.get("name") == "消息")
        items = [n for n in (messages.get("children") or []) if n.get("role") == "list item"] if messages else []
        return (items[-1].get("name") or "") if items else "", len(items)
    messages = find(tree, lambda n: n.get("name") == "消息列表")
    texts = [text_of(n) for n in walk(messages) if n.get("role") == "static" and text_of(n)] if messages else []
    return (texts[-1] if texts else ""), len(texts)


def qq_result_match(item, name):
    """How a QQ search result names `name`: "exact", "truncated" (a long name cut off with an ellipsis) or None.
    Results list the name in pieces followed by descriptions such as member counts or the matched message."""
    joined = ""
    for child in walk(item):
        piece = text_of(child) if child is not item and child.get("role") == "static" else ""
        if not piece:
            continue
        if piece in ("...", "…"):
            return "truncated" if len(joined) >= 4 and name.startswith(joined) else None
        joined += piece
        if joined == name:
            return "exact"
        if not name.startswith(joined):
            return None
    return None


def restore_from_tray(desktop, driver):
    """Shows a client whose window was hidden to the panel tray (WeChat's tray button is named, QQ's sits beside it)."""
    panel = next((s for s in desktop.call("/desktop").get("surfaces") or [] if s.get("title") == "面板"), None)
    if panel is None:
        return False
    tree = desktop.tree(panel["id"])
    tabs = [n for n in walk(tree) if n.get("role") == "page tab" and n.get("bounds")]
    start = max((n["bounds"]["x"] for n in tabs), default=0)
    tray = [n for n in walk(tree) if n.get("role") == "button" and n.get("bounds") and n["bounds"]["x"] > start
            and n.get("name") not in ("通知", "时钟", "显示桌面")]
    if driver == "wechat":
        target = next((n for n in tray if (n.get("name") or "").lower() == "wechat"), None)
    else:
        target = next((n for n in tray if (n.get("name") or "").lower() in ("qq", "")), None)
    if target is None:
        return False
    desktop.click(target["bounds"])
    time.sleep(2)
    return True


def open_conversation(desktop, driver, window_id, tree, name, folded):
    """Opens the chat named `name` and returns the window tree once its input belongs to that chat."""
    node, _ = chat_input(driver, tree, name)
    if node is not None:
        return tree
    desktop.activate(window_id)
    if driver == "wechat":
        folder = APPS[driver]["folder"]
        if folded:
            if wechat_find_row(desktop, window_id, "会话", folder) is None or \
                    not stable_click(desktop, window_id, row_locator(driver, "会话", folder)):
                raise AdapterError("conversation_not_found")
            time.sleep(1.2)
        list_name = folder if folded else "会话"
        if wechat_find_row(desktop, window_id, list_name, name) is None or \
                not stable_click(desktop, window_id, row_locator(driver, list_name, name)):
            raise AdapterError("conversation_not_found")
    else:
        # QQ's search results hold still while the chat list reorders, so chats are always opened from search.
        # The search box is QQ's only entry; it loses its "搜索" name once text has been typed and cleared.
        ref = desktop.ref(window_id, r'entry\b')
        if not ref:
            raise AdapterError("conversation_not_found")
        desktop.tool("type", ref=ref, text=name, replace=True)
        time.sleep(1.5)
        results = [n for n in walk(desktop.tree(window_id)) if n.get("role") == "list item" and n.get("bounds")]
        exact = [n for n in results if qq_result_match(n, name) == "exact"]
        truncated = [n for n in results if qq_result_match(n, name) == "truncated"]
        match = exact[0] if exact else (truncated[0] if len(truncated) == 1 else None)
        if match is None:
            # Escape would hide the client to the tray, so the search text is cleared by hand.
            desktop.tool("key", keys="ctrl+a")
            desktop.tool("key", keys="BackSpace")
            raise AdapterError("conversation_not_found")
        desktop.click(match["bounds"])
    time.sleep(1.5)
    tree = desktop.tree(window_id)
    node, _ = chat_input(driver, tree, name, loose=True)
    if node is None:
        raise AdapterError("conversation_open_failed")
    return tree


def type_text(desktop, driver, window_id, tree, name, body):
    lines = body.split("\n")
    node, _ = chat_input(driver, tree, name, loose=True)
    if node is None:
        raise AdapterError("input_not_found")
    if driver == "wechat":
        ref = desktop.ref(window_id, r'text "{}"'.format(re.escape(node.get("name") or name)))
        if not ref:
            raise AdapterError("input_not_found")
        desktop.tool("type", ref=ref, text=lines[0])
    else:
        desktop.click(node["bounds"])
        desktop.tool("type", text=lines[0])
    for line in lines[1:]:
        desktop.tool("key", keys="shift+Return")
        if line:
            desktop.tool("type", text=line)


def clear_input(desktop):
    desktop.tool("key", keys="ctrl+a")
    desktop.tool("key", keys="BackSpace")


def send(request, config):
    """One approved send. Failures before the text is sent report `dispatched: false`; once it may have gone out,
    a result that cannot be confirmed reports neither a receipt nor `dispatched: false`, which the runtime treats as
    uncertain and never retries on its own."""
    driver = request.get("driver")
    body = request.get("body") if isinstance(request.get("body"), str) else ""
    body = body.replace("\r\n", "\n").strip()
    if driver not in APPS:
        return {"ok": False, "dispatched": False, "error": "driver_unsupported"}
    if request.get("attachments"):
        return {"ok": False, "dispatched": False, "error": "attachments_unsupported"}
    if not body or len(body) > MAX_BODY:
        return {"ok": False, "dispatched": False, "error": "invalid_body"}
    conversation = request.get("conversationExternalId")
    try:
        desktop, _ = container(config, request.get("profile"))
        state = load_state()
        target = state["conversations"].get(conversation) if isinstance(conversation, str) else None
        if not target:
            return {"ok": False, "dispatched": False, "error": "conversation_unknown"}
        name = target["name"]
        window_id, tree = open_client(desktop, driver)
        desktop.activate(window_id)
        tree = open_conversation(desktop, driver, window_id, tree, name, bool(target.get("folder")))
        node, draft = chat_input(driver, tree, name, loose=True)
        if collapse(draft):
            return {"ok": False, "dispatched": False, "error": "draft_present"}
        before_text, before_count = last_message(driver, tree)
        type_text(desktop, driver, window_id, tree, name, body)
        time.sleep(0.6)
        tree = desktop.tree(window_id)
        node, typed = chat_input(driver, tree, name, loose=True)
        if node is None or collapse(typed) != collapse(body):
            clear_input(desktop)
            return {"ok": False, "dispatched": False, "error": "input_mismatch"}
    except AdapterError as error:
        return {"ok": False, "dispatched": False, "error": str(error)}

    try:
        if driver == "qq":
            ref = desktop.ref(window_id, r'button "发送"')
            if ref:
                desktop.tool("click", ref=ref)
            else:
                desktop.tool("key", keys="Return")
        else:
            desktop.tool("key", keys="Return")
        for _ in range(5):
            time.sleep(1)
            tree = desktop.tree(window_id)
            node, remaining = chat_input(driver, tree, name, loose=True)
            last, count = last_message(driver, tree)
            fresh = collapse(before_text) != collapse(body) or count != before_count
            if node is not None and not collapse(remaining) and collapse(last) == collapse(body) and fresh:
                now = int(time.time() * 1000)
                state["recent"].setdefault(conversation, []).append({"t": digest(collapse(body)), "at": now})
                save_state(state)
                return {"ok": True, "receipt": "{}:{}:{}".format(conversation, digest(body), now)}
    except AdapterError as error:
        print(str(error), file=sys.stderr)
    return {"ok": False, "error": "send_unverified"}


def handle(request):
    operation = request.get("op") if isinstance(request, dict) else None
    try:
        config = load_config()
    except AdapterError as error:
        if operation == "send":
            return {"ok": False, "dispatched": False, "error": str(error)}
        return {"ok": False, "sourceReadStatus": "failed", "error": str(error)}
    if operation == "send":
        return send(request, config)
    if operation != "scan":
        return {"ok": False, "error": "operation_unsupported"}
    try:
        return scan(request, config)
    except AdapterError as error:
        print(str(error), file=sys.stderr)
        return {"ok": False, "sourceReadStatus": "failed", "error": str(error)}


def main():
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sys.stdout.write(json.dumps(handle(request), ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
