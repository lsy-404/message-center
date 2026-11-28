#!/usr/bin/env python3
"""Device adapter for WeChat and QQ desktop clients running in a wechat-selkies container.

The runtime runs this executable once per request with one JSON object on stdin. Each profile names a container in
``selkies_adapter.json`` beside this file and a file holding the container's Selkies master token. A scan reads the
client's chat list, and the chats folded into 群助手 / 折叠的聊天, through the container's Pelorus accessibility API and
reports every chat whose last message changed. Input goes in with xdotool through ``docker exec``, since Pelorus pauses
about a second after every action it performs. Scans never open a chat, so nothing is marked read. A send opens the
chat, sends each file through the client's file picker and then the text, and checks the message list after each one
before it reports a receipt.
"""

import base64
import datetime
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib

REQUEST_TIMEOUT = 15
MAX_REMEMBERED = 300
AVATAR_REFRESH_MS = 7 * 24 * 60 * 60 * 1000
MAX_PROFILES = 20
MAX_BODY = 20000
MAX_STATE_CONVERSATIONS = 1000
FOLDER_REFRESH_MS = 10 * 60 * 1000
FULL_SCAN_MS = 5 * 60 * 1000
RECENT_SEND_MS = 15 * 60 * 1000
SCROLL_PAGES = 8
MAX_ATTACHMENTS = 20
OUTGOING_KEEP_S = 24 * 3600
FILE_SEND_WAIT_S = 90
CONFIG_PATH = os.path.splitext(os.path.abspath(__file__))[0] + ".json"
STATE_BASE = os.path.splitext(os.path.abspath(__file__))[0]

APPS = {
    "wechat": {"app_id": "wechat", "sign_in": ("扫码登录", "当前登录用户", "需在手机上完成登录"), "folder": "折叠的聊天", "prefix": "wx"},
    "qq": {"app_id": "QQ", "sign_in": ("手机QQ扫码登录", "输入QQ密码"), "folder": "群助手", "prefix": "qq"},
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
CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
INPUT_TIMEOUT = 20
# Each signed-in account leaves a marker here; the newest one is the account signed in now.
ACCOUNT_MARKERS = {
    "qq": ("/config/.config/QQ/global/nt_data/Login", re.compile(r"^\.([1-9][0-9]{4,11})$")),
    "wechat": ("/config/xwechat_files/all_users/login", re.compile(r"^(wxid_[A-Za-z0-9_-]{4,60}|[A-Za-z][A-Za-z0-9_-]{5,19})$")),
}
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
SAFE_FILE_NAME = re.compile(r"^[^/\\\x00-\x1f]{1,200}$")


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


def state_path(profile):
    """Each profile (one account) keeps its own chat names and recent sends."""
    if not isinstance(profile, str) or not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$", profile):
        raise AdapterError("profile_invalid")
    return "{}.{}.state.json".format(STATE_BASE, profile)


def load_state(profile):
    try:
        with open(state_path(profile), encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    state.setdefault("conversations", {})
    state.setdefault("recent", {})
    state.setdefault("avatars", {})
    state["profile"] = profile
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
    state["avatars"] = {key: at for key, at in state.get("avatars", {}).items() if key in state["conversations"]}
    path = state_path(state["profile"])
    directory = os.path.dirname(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".selkies-state-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, separators=(",", ":"))
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
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
    name, docker = entry.get("container"), config.get("docker")
    if not isinstance(name, str) or not CONTAINER_NAME.match(name) or not isinstance(docker, str) \
            or not os.path.isabs(docker):
        raise AdapterError("profile_invalid")
    return Desktop(url, "Bearer " + token, docker, name), entry


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise urllib.error.HTTPError(request.full_url, code, "redirect_refused", headers, response)


class Desktop:
    """The container's Pelorus API for windows, accessibility trees and pictures, and xdotool for input."""

    def __init__(self, url, authorization, docker, name):
        self.url = url
        self.authorization = authorization
        self.docker = docker
        self.name = name

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

    def exec(self, *command):
        try:
            return subprocess.run([self.docker, "exec", self.name, "env", "DISPLAY=:20"] + list(command),
                                  stdin=subprocess.DEVNULL, capture_output=True,
                                  timeout=INPUT_TIMEOUT, check=True).stdout.decode("utf-8", "replace")
        except (OSError, subprocess.SubprocessError):
            raise AdapterError("desktop_input_failed")

    def xdotool(self, *arguments):
        return self.exec("xdotool", *arguments)

    def pointer(self, *arguments):
        """The image's mc-input executor: moves the pointer along a human-like path before it clicks or scrolls."""
        return self.exec("mc-input", *[str(int(a)) if isinstance(a, (int, float)) else a for a in arguments])

    def control(self, window_id, pattern):
        return control_in(self.tree(window_id), pattern)

    def press(self, control):
        self.click(control["bounds"])

    def click(self, bounds, button="left"):
        self.pointer("click", bounds["x"], bounds["y"], max(1, bounds["w"]), max(1, bounds["h"]), button)

    def point(self, x, y):
        self.pointer("move", x - 3, y - 3, 6, 6)

    def scroll(self, at, direction, amount):
        self.pointer("scroll", at[0], at[1], direction, amount)

    def key(self, keys):
        self.xdotool("key", "--clearmodifiers", keys)

    def write(self, text):
        self.xdotool("type", "--delay", "8", "--", text)

    def activate(self, window_id):
        """Brings the window to the front the way a person would, by clicking its title bar when it is not focused;
        clicks and scrolls land on whatever window is on top."""
        desktop = self.call("/desktop")
        if desktop.get("focus") == window_id:
            return
        window = next((w for w in desktop.get("windows") or [] if w.get("id") == window_id), None)
        if not window or not window.get("frame"):
            raise AdapterError("window_missing")
        self.click(title_spot(window, self.tree(window_id)))
        time.sleep(0.2)

    def windows(self):
        return self.call("/desktop").get("windows") or []

    def account(self, driver):
        """The account signed in to the client, read from the client's own data directory."""
        directory, pattern = ACCOUNT_MARKERS[driver]
        try:
            listing = subprocess.run([self.docker, "exec", self.name, "ls", "-At", directory],
                                     stdin=subprocess.DEVNULL, capture_output=True, timeout=INPUT_TIMEOUT, check=True)
        except (OSError, subprocess.SubprocessError):
            raise AdapterError("account_unknown")
        for line in listing.stdout.decode("utf-8", "replace").splitlines():
            match = pattern.match(line.strip())
            if match:
                return match.group(1)
        raise AdapterError("account_unknown")

    def screenshot(self, window_id):
        """The window's picture as PNG bytes, and the (x, y, scale) that maps a screen point into it."""
        result = self.call("/tool", "POST", {"name": "screenshot", "arguments": {"window": window_id}})
        match = re.search(r"screen point (-?\d+),(-?\d+) and it is (\d+)x(\d+)", result.get("text") or "")
        image = (result.get("image") or "").split(",", 1)[-1]
        if result.get("failed") or not match or not image:
            raise AdapterError("desktop_action_failed")
        png = base64.b64decode(image)
        width = int.from_bytes(png[16:20], "big")
        return png, (int(match.group(1)), int(match.group(2)), width / max(1, int(match.group(3))))

    def park_pointer(self, window_id):
        """Moves the pointer onto the window's title bar so no list row is drawn hovered."""
        window = next((w for w in self.windows() if int(w.get("id", -1)) == window_id), None)
        if window and window.get("rect"):
            x, y, w, _ = window["rect"]
            self.point(x + w / 2, y + 12)


CONTROL_ROLES = {"button", "push button", "toggle button", "link", "entry", "password text", "page tab", "menu item",
                 "check box", "radio button", "combo box", "list item", "image", "static", "label"}


def title_spot(window, tree):
    """An empty patch of the window's title strip to click on: the window manager's title bar when the window has
    one, otherwise the top of the client's own drag area away from any control."""
    fx, fy, fw, _ = window["frame"]
    rx, ry = window["rect"][0], window["rect"][1]
    if ry - fy >= 12:
        return {"x": fx + fw * 0.3, "y": fy + 2, "w": fw * 0.4, "h": ry - fy - 4}
    controls = [n["bounds"] for n in walk(tree) if n.get("role") in CONTROL_ROLES and n.get("bounds")]
    for step in range(30, 70, 4):
        spot = {"x": rx + fw * step / 100, "y": ry + 2, "w": 24, "h": 10}
        if not any(b["x"] < spot["x"] + spot["w"] and spot["x"] < b["x"] + b["w"]
                   and b["y"] < spot["y"] + spot["h"] and spot["y"] < b["y"] + b["h"] for b in controls):
            return spot
    raise AdapterError("window_title_covered")


def control_in(tree, pattern):
    """The first control in `tree` whose ``role "name"`` line matches `pattern`, as Pelorus `look` writes it."""
    for node in walk(tree):
        name = node.get("name")
        line = "{} \"{}\"".format(node.get("role"), name) if name else str(node.get("role"))
        if node.get("bounds") and re.match(pattern, line):
            return node
    return None


def walk(node):
    yield node
    for child in node.get("children") or []:
        yield from walk(child)


def text_of(node):
    return (node.get("name") or node.get("text") or "").strip()


def find(tree, predicate):
    return next((node for node in walk(tree) if predicate(node)), None)


def type_into(desktop, text, control=None, replace=False):
    """Types `text` where the keyboard focus is, or into `control` after clicking it, first clearing the field with
    `replace`."""
    if control is not None:
        desktop.press(control)
    if replace:
        clear_input(desktop)
    desktop.write(text)


def png_left_columns(png, columns):
    """RGB(A) rows of an 8-bit, non-interlaced PNG, each cut to its first `columns` pixels. PNG filters only refer to
    the pixels left of and above a byte, so decoding that prefix of every row is exact and avoids decoding the rest."""
    position, chunks, header = 8, [], None
    while position + 8 <= len(png):
        length = int.from_bytes(png[position:position + 4], "big")
        kind = png[position + 4:position + 8]
        data = png[position + 8:position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            header = data
        elif kind == b"IDAT":
            chunks.append(data)
    if header is None or header[8] != 8 or header[9] not in (2, 6) or header[12] != 0:
        raise AdapterError("screenshot_unsupported")
    width, height = int.from_bytes(header[0:4], "big"), int.from_bytes(header[4:8], "big")
    bpp = 4 if header[9] == 6 else 3
    raw = zlib.decompress(b"".join(chunks))
    stride, span = width * bpp + 1, min(columns, width) * bpp
    rows, previous = [], bytearray(span)
    for y in range(height):
        kind = raw[y * stride]
        line = bytearray(raw[y * stride + 1:y * stride + 1 + span])
        for i in range(span):
            left = line[i - bpp] if i >= bpp else 0
            up = previous[i]
            if kind == 1:
                line[i] = (line[i] + left) & 255
            elif kind == 2:
                line[i] = (line[i] + up) & 255
            elif kind == 3:
                line[i] = (line[i] + ((left + up) >> 1)) & 255
            elif kind == 4:
                corner = previous[i - bpp] if i >= bpp else 0
                estimate = left + up - corner
                distances = abs(estimate - left), abs(estimate - up), abs(estimate - corner)
                line[i] = (line[i] + (left if distances[0] <= distances[1] and distances[0] <= distances[2]
                                      else up if distances[1] <= distances[2] else corner)) & 255
        rows.append(bytes(line))
        previous = line
    return rows, bpp


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


def qq_open_chat(tree):
    """The open chat's name: the input box carries it while it holds text, the chat header's leftmost button always."""
    node = find(tree, lambda n: n.get("role") == "section" and (n.get("states") or {}).get("editable") and n.get("name"))
    if node:
        return node.get("name")
    header = [n for n in walk(tree) if n.get("role") == "button" and text_of(n) and n.get("bounds")
              and n["bounds"]["x"] > 300 and 40 < n["bounds"]["y"] < 120]
    return min(header, key=lambda n: n["bounds"]["x"]).get("name") if header else None


def qq_scroll_top(desktop, window_id, tree):
    """Scrolls the chat list until its first row sits at the list's top edge; QQ sometimes takes a burst of wheel
    steps as one, so the position is checked after each burst."""
    for _ in range(4):
        chats = find(tree, lambda n: n.get("name") == "会话列表")
        bounds = chats.get("bounds") if chats else None
        if not bounds:
            return tree
        first = next((c for c in chats.get("children") or [] if c.get("bounds")), None)
        if first and first["bounds"]["y"] >= bounds["y"]:
            return tree
        desktop.scroll([bounds["x"] + bounds["w"] / 2, bounds["y"] + bounds["h"] / 2], "up", 30)
        time.sleep(0.3)
        tree = desktop.tree(window_id)
    return tree


def qq_mark_pinned(desktop, window_id, rows, open_name):
    """QQ draws pinned rows on their own background and does not say so in the accessibility tree, so each row's
    background is sampled from a screenshot: a row whose colour differs from the most common row colour is pinned.
    The open chat's row is highlighted either way; it and any row that cannot be sampled get `pinned: None`."""
    for row in rows:
        row["pinned"] = None
    placed = [row for row in rows if row.get("bounds")]
    if len(placed) < 5:
        return rows
    desktop.park_pointer(window_id)
    time.sleep(0.3)
    png, (left, top, scale) = desktop.screenshot(window_id)
    points = [(row, int((row["bounds"]["x"] + 3 - left) * scale),
               int((row["bounds"]["y"] + row["bounds"]["h"] / 2 - top) * scale)) for row in placed]
    points = [(row, x, y) for row, x, y in points if x >= 0 and y >= 0]
    if not points:
        return rows
    pixels, bpp = png_left_columns(png, max(x for _, x, _ in points) + 1)
    colours = [(row, pixels[y][x * bpp:x * bpp + 3]) for row, x, y in points if y < len(pixels)]
    tally = {}
    for _, colour in colours:
        tally[colour] = tally.get(colour, 0) + 1
    if not tally:
        return rows
    common = max(tally, key=tally.get)
    for row, colour in colours:
        if row["name"] != open_name:
            row["pinned"] = colour != common
    # The list puts pinned chats first and the rest newest first: an open chat below an unpinned chat is not pinned,
    # and one older than an unpinned chat below it is.
    for index, row in enumerate(rows):
        if row["pinned"] is not None or row["name"] != open_name:
            continue
        if any(other["pinned"] is False for other in rows[:index]):
            row["pinned"] = False
        elif time_rank(row["time"]) is not None and any(
                other["pinned"] is False and (time_rank(other["time"]) or (-1,)) > time_rank(row["time"])
                for other in rows[index + 1:]):
            row["pinned"] = True
    return rows


def time_rank(label):
    """A sortable key for a chat-list time label (16:30, 昨天, 前天, 11/17, 2025/11/17); None for others."""
    match = re.match(r"^(\d{1,2}):(\d{2})$", label or "")
    if match:
        return (5, int(match.group(1)) * 60 + int(match.group(2)))
    if label in ("昨天", "前天"):
        return (4 if label == "昨天" else 3, 0)
    match = re.match(r"^(\d{1,2})/(\d{1,2})$", label or "")
    if match:
        return (1, int(match.group(1)) * 100 + int(match.group(2)))
    match = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})$", label or "")
    if match:
        return (0, int(match.group(1)) * 10000 + int(match.group(2)) * 100 + int(match.group(3)))
    return None


def in_folder(driver, tree):
    if driver == "wechat":
        return find(tree, lambda n: n.get("role") == "list" and n.get("name") == APPS[driver]["folder"]) is not None
    return find(tree, lambda n: n.get("role") == "static" and n.get("name") == "返回") is not None


def leave_folder(desktop, driver, window_id, tree):
    if driver == "wechat":
        back = desktop.control(window_id, r'button "返回"')
        if back:
            desktop.press(back)
    else:
        back = find(tree, lambda n: n.get("role") == "static" and n.get("name") == "返回")
        if back and back.get("bounds"):
            desktop.click(back["bounds"])
    time.sleep(1)


def main_rows(driver, tree):
    return wechat_rows(tree) if driver == "wechat" else qq_rows(tree)


def check_account(desktop, driver, request):
    """Refuses to act for a connector whose id names another account than the one signed in."""
    if desktop.account(driver) != request.get("account"):
        raise AdapterError("account_mismatch")


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
            tab = desktop.control(window_id, r'toggle button "消息"' if driver == "qq" else r'button "(WeChat|微信)"')
            if not tab:
                continue
            desktop.press(tab)
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
    def visible_rows():
        chats = find(desktop.tree(window_id), lambda n: n.get("role") == "list" and n.get("name") == list_name)
        return wechat_list_rows(chats, "normal") if chats else []
    # The client drops wheel notches that arrive close together, so scroll up until the rows stop changing.
    previous = None
    for _ in range(SCROLL_PAGES):
        desktop.scroll(center, "up", 15)
        time.sleep(0.4)
        names = [row["name"] for row in visible_rows()]
        if names == previous:
            break
        previous = names
    previous = None
    for _ in range(SCROLL_PAGES):
        rows = visible_rows()
        for row in rows:
            if row["bounds"] and (row["name"] == name or (row["selected"] and name.startswith(row["name"]))):
                return row
        names = [row["name"] for row in rows]
        if names == previous:
            return None
        previous = names
        desktop.scroll(center, "down", 5)
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
        desktop.scroll(center, "up", 30)


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
            folded = qq_mark_pinned(desktop, window_id, [dict(r, placement="folded") for r in folded],
                                    qq_open_chat(tree))
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
        if now - entry.get("at", 0) < RECENT_SEND_MS and (entry.get("t") in wanted or set(entry.get("ts") or ()) & wanted):
            del entries[index]
            return True
    return False


def row_traits(row):
    return "{}{}{}".format(int(bool(row["muted"])), int(bool(row["pinned"])), row["placement"][0])


def folder_print(row):
    return digest("{}\n{}".format(row["preview"], row["unread"]))


def rows_known(driver, rows, seen, folder_seen):
    """Whether the chat list as read, before any scrolling or pin sampling, shows nothing the last full scan did not:
    every row's preview and mute state as last seen, no unread count grown, and the folder row as it was when the
    folder is read at all (`folder_seen`). QQ pins need a screenshot, so they are compared on full scans only."""
    if not rows:
        return False
    prefix = APPS[driver]["prefix"]
    for row in rows:
        if row["name"] == APPS[driver]["folder"]:
            if folder_seen is not None and folder_print(row) != folder_seen:
                return False
            continue
        if row["name"] in AGGREGATES[driver] or not row["preview"]:
            continue
        previous = seen.get("{}-{}".format(prefix, digest(row["name"])))
        unread = row["unread"] if isinstance(row["unread"], int) else 0
        if previous is None or previous.get("p") != digest(row["preview"]) or unread > previous.get("u", 0):
            return False
        traits, known = row_traits(row), previous.get("s") or ""
        if (traits != known) if driver == "wechat" else (traits[0] + traits[2:] != known[:1] + known[2:]):
            return False
    return True


class RowPictures:
    """Chat-list row avatars cut from one screenshot taken while the main chat list is on screen."""

    def __init__(self, desktop, window_id, rows):
        right = max((r["bounds"]["x"] + 90 for r in rows if r.get("bounds")), default=0)
        self.shot = None
        if right:
            png, (self.left, self.top, self.scale) = desktop.screenshot(window_id)
            self.rows, self.bpp = png_left_columns(png, int((right - self.left) * self.scale))
            self.shot = True

    def avatar(self, bounds):
        """The square picture at the row's left end, found as the ink that differs from the row's own background."""
        if not self.shot or not bounds:
            return None
        bpp, scale = self.bpp, self.scale
        x0, y0 = int((bounds["x"] - self.left) * scale), int((bounds["y"] - self.top) * scale)
        x1, y1 = x0 + int(80 * scale), min(len(self.rows), y0 + int(bounds["h"] * scale))
        if y0 < 0 or y1 - y0 < 16:
            return None
        background = self.rows[y0 + 2][(x0 + 2) * bpp:(x0 + 2) * bpp + 3]
        inked = [(x, y) for y in range(y0, y1) for x in range(x0, x1)
                 if max(abs(a - b) for a, b in zip(self.rows[y][x * bpp:x * bpp + 3], background)) > 24]
        if len(inked) < 200:
            return None
        left, top = min(x for x, _ in inked), min(y for _, y in inked)
        size = min(max(x for x, _ in inked) - left, max(y for _, y in inked) - top) + 1
        if size < 20 or size > 72:
            return None
        return png_encode([row[left * bpp:(left + size) * bpp] for row in self.rows[top:top + size]], size, bpp)


def scan(request, config):
    driver = request.get("driver")
    if driver not in APPS:
        raise AdapterError("driver_unsupported")
    desktop, entry = container(config, request.get("profile"))
    state = load_state(request.get("profile"))
    window_id, tree = open_client(desktop, driver)
    check_account(desktop, driver, request)
    owner = qq_owner(tree) if driver == "qq" else None
    cursor = request.get("cursor") if isinstance(request.get("cursor"), dict) else {}
    seen = dict(cursor.get("chats") or {})
    folder_state = dict(cursor.get("folder") or {})
    limit = max(1, min(int(request.get("limit") or 20), 20))
    now = int(time.time() * 1000)
    full_at = cursor.get("full") if isinstance(cursor.get("full"), int) else 0

    rows = main_rows(driver, tree) or []
    pictures_due = any(r.get("bounds") and not r["unread"] and r["name"] not in AGGREGATES[driver] and
                       now - state["avatars"].get("{}-{}".format(APPS[driver]["prefix"], digest(r["name"])), 0)
                       > AVATAR_REFRESH_MS for r in rows)
    if now - full_at < FULL_SCAN_MS and not pictures_due and rows_known(driver, rows, seen, cursor.get("a")):
        return {"ok": True, "sourceReadStatus": "complete", "health": "online", "cursor": cursor,
                "messages": [], "conversationProfiles": [], "active": True, "more": False}
    if driver == "qq":
        desktop.activate(window_id)
        tree = qq_scroll_top(desktop, window_id, tree)
        rows = qq_mark_pinned(desktop, window_id, main_rows(driver, tree) or [], qq_open_chat(tree))

    on_screen = {id(r) for r in rows if r.get("bounds")}

    def wants_avatar(row):
        # An unread badge sits on WeChat's avatars, so pictures are taken from read rows.
        key = "{}-{}".format(APPS[driver]["prefix"], digest(row["name"]))
        return (id(row) in on_screen and not row["unread"] and row["name"] not in AGGREGATES[driver]
                and now - state["avatars"].get(key, 0) > AVATAR_REFRESH_MS)
    pictures = RowPictures(desktop, window_id, [r for r in rows if wants_avatar(r)]) \
        if any(wants_avatar(r) for r in rows) else None

    aggregate = next((r for r in rows if r["name"] == APPS[driver]["folder"]), None)
    aggregate_print = folder_print(aggregate) if aggregate else None
    due = (aggregate_print and folder_state.get("p") != aggregate_print) or now - folder_state.get("at", 0) >= FOLDER_REFRESH_MS
    # A pinned folder row cannot move, so opening it is safe without the readFolders opt-in.
    readable = entry.get("readFolders") is True or bool(aggregate and aggregate.get("pinned"))
    if readable and due:
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
        if row["pinned"] is None:
            row["pinned"] = bool(previous and len(previous.get("s") or "") > 1 and previous["s"][1] == "1")
        traits = row_traits(row)
        changed = previous is None or previous.get("p") != fingerprint or unread > previous.get("u", 0)
        picture = pictures.avatar(row["bounds"]) if pictures and wants_avatar(row) else None
        if not changed and previous.get("s") == traits and picture is None:
            continue
        if (changed and len(messages) >= limit) or len(profiles) >= MAX_PROFILES:
            more = True
            continue
        if changed and not own_echo(state, conversation, [row["preview"], body], now):
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
                   "pinned": bool(row["pinned"]), "muted": bool(row["muted"])}
        if changed:
            profile["lastMessagePreview"] = row["preview"][:500]
            profile["lastMessageAt"] = iso(now)
        if isinstance(row["unread"], int):
            profile["unreadCount"] = row["unread"]
            profile["unreadObservedAt"] = iso(now)
        if picture is not None and sum(len(p.get("avatarBase64", "")) for p in profiles) < 120_000:
            profile["avatarBase64"] = base64.b64encode(picture).decode("ascii")
            state["avatars"][conversation] = now
        profiles.append(profile)
        seen[conversation] = {"p": fingerprint, "u": unread, "g": group, "s": traits,
                              "at": now if changed else previous.get("at", now)}
    save_state(state)
    kept = sorted(seen.items(), key=lambda item: -item[1].get("at", 0))[:MAX_REMEMBERED]
    return {"ok": True, "sourceReadStatus": "complete", "health": "online",
            "cursor": {"chats": dict(kept), "folder": folder_state, "full": now, "a": aggregate_print if readable else None},
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
    # Only called with no client window mapped, so the panel has no task button for the client to confuse with.
    tray = [n for n in walk(tree) if n.get("role") == "button" and n.get("bounds")
            and n.get("name") not in ("开始菜单", "通知", "时钟", "显示桌面")]
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
            wait_for(lambda: in_folder(driver, desktop.tree(window_id)), 3)
        list_name = folder if folded else "会话"
        if wechat_find_row(desktop, window_id, list_name, name) is None or \
                not stable_click(desktop, window_id, row_locator(driver, list_name, name)):
            raise AdapterError("conversation_not_found")
    else:
        # QQ's search results hold still while the chat list reorders, so chats are always opened from search.
        # The search box is QQ's only entry; it loses its "搜索" name once text has been typed and cleared.
        # Activating the maximized window moves nothing, so the tree read before it still places the controls.
        search = control_in(tree, r'entry\b')
        if not search:
            raise AdapterError("conversation_not_found")
        type_into(desktop, name, search, replace=True)
        results = []

        def exact_listed():
            results[:] = [n for n in walk(desktop.tree(window_id)) if n.get("role") == "list item" and n.get("bounds")]
            return any(qq_result_match(n, name) == "exact" for n in results)
        wait_for(exact_listed, 3, every=0.1)
        exact = [n for n in results if qq_result_match(n, name) == "exact"]
        truncated = [n for n in results if qq_result_match(n, name) == "truncated"]
        match = exact[0] if exact else (truncated[0] if len(truncated) == 1 else None)
        if match is None:
            # Escape would hide the client to the tray, so the search text is cleared by hand.
            clear_input(desktop)
            raise AdapterError("conversation_not_found")
        desktop.click(match["bounds"])

    def opened():
        tree = desktop.tree(window_id)
        return tree if chat_input(driver, tree, name, loose=True)[0] is not None else None
    tree = wait_for(opened, 4, every=0.1)
    if tree is None:
        raise AdapterError("conversation_open_failed")
    return tree


def mention_parts(body, mentions):
    """`body` split into (is_mention, text) pieces, a mention being "@<name>" for a name in `mentions`."""
    names = sorted({m for m in mentions if m}, key=len, reverse=True)
    parts, start, index = [], 0, 0
    while index < len(body):
        hit = next((n for n in names if body.startswith("@" + n, index)), None)
        if hit is None:
            index += 1
            continue
        if index > start:
            parts.append((False, body[start:index]))
        parts.append((True, hit))
        index += len(hit) + 1
        start = index
    if start < len(body):
        parts.append((False, body[start:]))
    return parts


def without_mentions(text, mentions):
    """`text` with mention pills (WeChat shows each as U+FFFC) and "@<name>" pieces removed, whitespace collapsed."""
    for name in sorted(mentions, key=len, reverse=True):
        text = text.replace("@" + name, "")
    return collapse(text.replace("\ufffc", ""))


def pick_mention(desktop, driver, window_id, name):
    """After "@<name>" was typed, chooses the member from the client's suggestion list. WeChat's list is a small
    window of its own whose rows are not in the tree and whose first row is the best match; QQ lists members in the
    chat window."""
    if driver == "wechat":
        popup = wait_for(lambda: any(w.get("app_id") == "wechat" and w.get("type") == "utility" and w.get("mapped")
                                     for w in desktop.windows()), 2, every=0.1)
        if not popup:
            raise AdapterError("mention_unavailable")
        # Return without the list open would send the draft.
        desktop.key("Return")
        return

    def option():
        return next((n for n in walk(desktop.tree(window_id)) if n.get("bounds")
                     and n.get("role") in ("list item", "menu item", "option")
                     and (text_of(n) == name or text_of(n).startswith(name + " ") or
                          any(text_of(c) == name for c in walk(n) if c is not n))), None)
    item = wait_for(option, 2, every=0.1)
    if item is None:
        raise AdapterError("mention_unavailable")
    desktop.click(item["bounds"])


def type_text(desktop, driver, window_id, tree, name, body, mentions=()):
    node, _ = chat_input(driver, tree, name, loose=True)
    if node is None or not node.get("bounds"):
        raise AdapterError("input_not_found")
    desktop.press(node)
    for is_mention, text in mention_parts(body, mentions):
        if is_mention:
            desktop.write("@")
            time.sleep(0.3)
            desktop.write(text)
            pick_mention(desktop, driver, window_id, text)
            time.sleep(0.2)
            continue
        lines = text.split("\n")
        if lines[0]:
            desktop.write(lines[0])
        for line in lines[1:]:
            desktop.key("shift+Return")
            if line:
                desktop.write(line)


def clear_input(desktop):
    desktop.key("ctrl+a")
    desktop.key("BackSpace")


def outgoing_files(entry, attachments, command_id):
    """Copies each attachment into the profile's outgoing directory, which the container mounts, under its own file
    name (recipients see it) in a fresh folder; returns (attachment, path inside the container) pairs."""
    host = os.path.expanduser(str(entry.get("outgoingDirectory") or ""))
    inside = str(entry.get("containerOutgoingDirectory") or "").rstrip("/")
    if not host or not os.path.isabs(host) or not inside.startswith("/"):
        raise AdapterError("attachments_unconfigured")
    os.makedirs(host, mode=0o755, exist_ok=True)
    now = time.time()
    with os.scandir(host) as entries:
        for item in entries:
            try:
                if item.is_dir(follow_symlinks=False) and now - item.stat(follow_symlinks=False).st_mtime > OUTGOING_KEEP_S:
                    shutil.rmtree(item.path, ignore_errors=True)
            except OSError:
                pass
    folder = "{}-{}".format(digest(str(command_id))[:10], secrets.token_hex(4))
    os.mkdir(os.path.join(host, folder), 0o755)
    staged = []
    for attachment in attachments:
        target = os.path.join(host, folder, attachment["fileName"])
        shutil.copyfile(attachment["localPath"], target)
        os.chmod(target, 0o644)
        staged.append((attachment, "{}/{}/{}".format(inside, folder, attachment["fileName"])))
    return staged


def dialog_windows(desktop):
    return {int(w["id"]): w for w in desktop.windows() if w.get("type") == "dialog" and w.get("mapped")}


def pick_file(desktop, driver, window_id, button, path):
    """Opens the chat's file picker with the toolbar `button` and chooses `path` in it. WeChat's picker is a Qt dialog
    with an accessible file name field; QQ's is a GTK dialog without accessibility, driven from its location bar."""
    control = desktop.control(window_id, r'button "{}"'.format(re.escape(button)))
    if not control:
        raise AdapterError("file_button_not_found")
    before = set(dialog_windows(desktop))
    desktop.press(control)
    dialog = None
    for _ in range(10):
        time.sleep(0.5)
        opened = [key for key in dialog_windows(desktop) if key not in before]
        if opened:
            dialog = opened[0]
            break
    if dialog is None:
        raise AdapterError("file_dialog_missing")
    if driver == "wechat":
        field = desktop.control(dialog, r'text "文件名称')
        if field:
            type_into(desktop, path, field, replace=True)
            desktop.key("Return")
    else:
        desktop.activate(dialog)
        desktop.key("ctrl+l")
        time.sleep(0.4)
        desktop.write(path)
        time.sleep(0.3)
        desktop.key("Return")
    for _ in range(10):
        time.sleep(0.5)
        if dialog not in dialog_windows(desktop):
            return
    desktop.tool("window", action="close", window=dialog)
    raise AdapterError("file_not_chosen")


def message_tail(driver, tree):
    """The last entries of the open chat's message list: list item names in WeChat, (role, text) leaves in QQ."""
    if driver == "wechat":
        messages = find(tree, lambda n: n.get("role") == "list" and n.get("name") == "消息")
        return [n.get("name") or "" for n in (messages.get("children") or []) if n.get("role") == "list item"][-6:] \
            if messages else []
    messages = find(tree, lambda n: n.get("name") == "消息列表")
    leaves = [(n.get("role"), text_of(n)) for n in walk(messages)
              if n.get("role") == "image" or (n.get("role") == "static" and text_of(n))] if messages else []
    return leaves[-16:]


def file_landed(driver, tail, before, attachment, as_image):
    if tail == before or not tail:
        return False
    name = attachment["fileName"]
    if driver == "wechat":
        last = tail[-1]
        if last.startswith("文件\n" + name + "\n"):
            return True
        return as_image and last in ("图片", "动画表情")
    if as_image:
        return tail[-1][0] == "image"
    statics = [text for role, text in tail if role == "static"]
    return bool(statics) and statics[-1].endswith("已发送") and name in "".join(statics)


def qq_file_confirmation(tree, name, file_name):
    """QQ asks before sending a file: "发送给 <chat>", the file name, and a 发送(n) button."""
    target = find(tree, lambda n: n.get("role") == "static" and text_of(n).startswith("发送给 "))
    if target is None:
        return False
    chat = text_of(target)[len("发送给 "):].rstrip("…. ")
    if not chat or not (chat == name or name.startswith(chat)):
        return False
    return any(n.get("role") == "paragraph" and "".join(text_of(c) for c in walk(n) if c is not n) == file_name
               for n in walk(tree))


def send_file(desktop, driver, window_id, name, attachment, path):
    """Puts one file in the chat and sends it. Returns the tail to verify against; raises AdapterError before the
    file is sent and returns normally once the client was told to send it."""
    tree = desktop.tree(window_id)
    before = message_tail(driver, tree)
    as_image = attachment["mimeType"] in IMAGE_TYPES
    if driver == "wechat":
        pick_file(desktop, driver, window_id, "发送文件", path)
        time.sleep(0.8)
        node, held = chat_input(driver, desktop.tree(window_id), name, loose=True)
        if node is None or collapse(held) != "￼":
            clear_input(desktop)
            raise AdapterError("input_mismatch")
        desktop.key("Return")
        return before, as_image
    image_button = as_image and desktop.control(window_id, r'button "图片"')
    if image_button:
        pick_file(desktop, driver, window_id, "图片", path)
        time.sleep(0.8)
        node, _ = chat_input(driver, desktop.tree(window_id), name, loose=True)
        held = "".join(text_of(n) or (n.get("text") or "") for n in walk(node) if n.get("role") == "paragraph") \
            if node else ""
        if node is None or re.sub(r"[\s​]", "", held) != "￼":
            clear_input(desktop)
            raise AdapterError("input_mismatch")
        send_button = desktop.control(window_id, r'button "发送"')
        if not send_button:
            clear_input(desktop)
            raise AdapterError("send_button_not_found")
        desktop.press(send_button)
        return before, True
    pick_file(desktop, driver, window_id, "文件", path)
    time.sleep(1)
    tree = desktop.tree(window_id)
    send_button = desktop.control(window_id, r'button "发送\(\d+\)"')
    if not send_button or not qq_file_confirmation(tree, name, attachment["fileName"]):
        close = desktop.control(window_id, r'button "关闭"')
        if close:
            desktop.press(close)
        raise AdapterError("file_confirmation_mismatch")
    desktop.press(send_button)
    return before, False


def wait_for(check, seconds, every=0.3):
    """Polls `check` until it returns something truthy or `seconds` pass; returns its last result."""
    deadline = time.time() + seconds
    while True:
        time.sleep(every)
        result = check()
        if result or time.time() >= deadline:
            return result


def echo_texts(attachment):
    """Chat-list previews the client may show for a file this adapter sent."""
    name = attachment["fileName"]
    if attachment["mimeType"] in IMAGE_TYPES:
        return ["[图片]", "[动画表情]", "[表情]", name, "[文件]" + name]
    return [name, "[文件]" + name, "[文件] " + name]


def valid_attachments(request):
    attachments = request.get("attachments") or []
    if not isinstance(attachments, list) or len(attachments) > MAX_ATTACHMENTS:
        return None
    for attachment in attachments:
        if not isinstance(attachment, dict) or not isinstance(attachment.get("fileName"), str) \
                or not SAFE_FILE_NAME.match(attachment["fileName"]) or attachment["fileName"] in (".", "..") \
                or attachment["fileName"].startswith(".") or not isinstance(attachment.get("mimeType"), str) \
                or not isinstance(attachment.get("localPath"), str) or not os.path.isfile(attachment["localPath"]):
            return None
    return attachments


def send(request, config):
    """One approved send: each file, then the text. Failures before anything was sent report `dispatched: false`;
    once something may have gone out, a result that cannot be confirmed reports neither a receipt nor
    `dispatched: false`, which the runtime treats as uncertain and never retries on its own."""
    driver = request.get("driver")
    body = request.get("body") if isinstance(request.get("body"), str) else ""
    body = body.replace("\r\n", "\n").strip()
    if driver not in APPS:
        return {"ok": False, "dispatched": False, "error": "driver_unsupported"}
    attachments = valid_attachments(request)
    if attachments is None:
        return {"ok": False, "dispatched": False, "error": "invalid_attachments"}
    if (not body and not attachments) or len(body) > MAX_BODY:
        return {"ok": False, "dispatched": False, "error": "invalid_body"}
    mentions = request.get("mentions") or []
    if not isinstance(mentions, list) or len(mentions) > 10 or not all(
            isinstance(m, str) and 0 < len(m) <= 64 and "\n" not in m and "@" + m in body for m in mentions):
        return {"ok": False, "dispatched": False, "error": "invalid_mentions"}
    conversation = request.get("conversationExternalId")
    dispatched = False

    def refused(error):
        # After a file went out, a later refusal still leaves the command partly sent.
        return {"ok": False, "error": error} if dispatched else {"ok": False, "dispatched": False, "error": error}

    try:
        desktop, entry = container(config, request.get("profile"))
        state = load_state(request.get("profile"))
        target = state["conversations"].get(conversation) if isinstance(conversation, str) else None
        if not target:
            return refused("conversation_unknown")
        name = target["name"]
        staged = outgoing_files(entry, attachments, request.get("commandId")) if attachments else []
        window_id, tree = open_client(desktop, driver)
        check_account(desktop, driver, request)
        # open_conversation raises the window when it has to open the chat; an open chat's input is checked after typing.
        tree = open_conversation(desktop, driver, window_id, tree, name, bool(target.get("folder")))
        node, draft = chat_input(driver, tree, name, loose=True)
        if collapse(draft):
            return refused("draft_present")
        for attachment, path in staged:
            before, as_image = send_file(desktop, driver, window_id, name, attachment, path)
            dispatched = True
            if not wait_for(lambda: file_landed(driver, message_tail(driver, desktop.tree(window_id)), before,
                                                attachment, as_image), FILE_SEND_WAIT_S):
                return {"ok": False, "error": "send_unverified"}
        now = int(time.time() * 1000)
        if not body:
            state["recent"].setdefault(conversation, []).append(
                {"ts": [digest(collapse(text)) for text in echo_texts(attachments[-1])], "at": now})
            save_state(state)
            return {"ok": True, "receipt": "{}:{}:{}".format(conversation, digest(json.dumps(
                [a["fileName"] for a in attachments], ensure_ascii=False)), now)}
        if staged:
            tree = desktop.tree(window_id)
        before_text, before_count = last_message(driver, tree)
        try:
            type_text(desktop, driver, window_id, tree, name, body, mentions)
        except AdapterError:
            clear_input(desktop)
            raise
        wanted = sum(1 for is_mention, _ in mention_parts(body, mentions) if is_mention)

        def typed_in():
            current = desktop.tree(window_id)
            node, typed = chat_input(driver, current, name, loose=True)
            if node is None:
                return None
            if not mentions:
                return current if collapse(typed) == collapse(body) else None
            pills = typed.count("\ufffc") + sum(typed.count("@" + m) for m in mentions)
            return current if pills >= wanted and without_mentions(typed, mentions) == without_mentions(body, mentions) \
                else None
        tree = wait_for(typed_in, 2, every=0.1)
        if not tree:
            clear_input(desktop)
            return refused("input_mismatch")
    except AdapterError as error:
        return refused(str(error))
    except OSError:
        return refused("attachment_staging_failed")

    try:
        send_button = control_in(tree, r'button "发送"') if driver == "qq" else None
        if send_button:
            desktop.press(send_button)
        else:
            desktop.key("Return")
        deadline = time.time() + 5
        while time.time() < deadline:
            time.sleep(0.1)
            tree = desktop.tree(window_id)
            node, remaining = chat_input(driver, tree, name, loose=True)
            last, count = last_message(driver, tree)
            fresh = collapse(before_text) != collapse(body) or count != before_count
            landed = collapse(last) == collapse(body) or (
                mentions and count != before_count and without_mentions(last, mentions) == without_mentions(body, mentions))
            if node is not None and not collapse(remaining) and landed and fresh:
                now = int(time.time() * 1000)
                state["recent"].setdefault(conversation, []).append({"t": digest(collapse(body)), "at": now})
                save_state(state)
                return {"ok": True, "receipt": "{}:{}:{}".format(conversation, digest(body), now)}
    except AdapterError as error:
        print(str(error), file=sys.stderr)
    return {"ok": False, "error": "send_unverified"}


WECHAT_TIME_ROW = re.compile(r"^(昨天|前天|星期[一二三四五六日天]|\d{4}年|\d{1,2}月\d{1,2}日)?\s*\d{1,2}:\d{2}$")
WECHAT_NOTICE_ROW = re.compile(r"拍了拍|撤回了一条消息|加入了群聊|邀请|移出了群聊|修改群名|以下为新消息|收到红包|领取了")


def wechat_avatars(desktop, window_id, messages):
    """Avatar squares down the message list's left (others) and right (own) edges, read from a screenshot:
    [(top, left_side, bounds)] from top to bottom. Each message row carries one avatar and time and notice rows none."""
    box = messages["bounds"]
    png, (left, top, scale) = desktop.screenshot(window_id)
    rows, bpp = png_left_columns(png, int((box["x"] + box["w"] - left) * scale))
    def px(x, y):
        return rows[int((y - top) * scale)][int((x - left) * scale) * bpp:int((x - left) * scale) * bpp + 3]
    background = px(box["x"] + box["w"] // 2, box["y"] + 4)
    found = []
    for side, x0 in ((True, box["x"] + 20), (False, box["x"] + box["w"] - 58)):
        start = None
        for y in range(box["y"], box["y"] + box["h"]):
            ink = sum(1 for x in range(x0, x0 + 36, 2) if max(abs(a - b) for a, b in zip(px(x, y), background)) > 24)
            if ink >= 6 and start is None:
                start = y
            elif ink < 6 and start is not None:
                if 24 <= y - start <= 48:
                    found.append((start, side, {"x": x0 + 4, "y": start + 4, "w": 28, "h": y - start - 8}))
                start = None
    return sorted(found, key=lambda item: item[0])


def wechat_pat_target(desktop, window_id, tree, message_text):
    """The avatar beside the newest visible message from someone else whose text is `message_text` (a chat-list
    preview, so possibly cut short with an ellipsis), matching message rows to avatars from the bottom up."""
    messages = find(tree, lambda n: n.get("role") == "list" and n.get("name") == "消息")
    if not messages or not messages.get("bounds"):
        raise AdapterError("message_list_missing")
    items = [n.get("name") or "" for n in (messages.get("children") or []) if n.get("role") == "list item"]
    items = [t for t in items if not WECHAT_TIME_ROW.match(t.strip()) and not WECHAT_NOTICE_ROW.search(t)]
    avatars = wechat_avatars(desktop, window_id, messages)
    wanted = collapse(message_text).rstrip("…").rstrip(".")
    for item, (_, others, bounds) in zip(reversed(items), reversed(avatars)):
        if others and wanted and collapse(item).startswith(wanted):
            return bounds
    raise AdapterError("pat_target_not_visible")


def pointer_at(desktop):
    found = dict(re.findall(r"(\w+)=(-?\d+)", desktop.xdotool("getmouselocation", "--shell")))
    return int(found["X"]), int(found["Y"])


def pat(request, config):
    """Pats the member who sent a group message: right-clicks their avatar beside the message and picks 拍一拍.
    The client then adds a notice naming whom it patted, which is the receipt."""
    driver = request.get("driver")
    sender = request.get("senderName") if isinstance(request.get("senderName"), str) else ""
    message_text = request.get("messageText") if isinstance(request.get("messageText"), str) else ""
    conversation = request.get("conversationExternalId")
    if driver not in APPS:
        return {"ok": False, "dispatched": False, "error": "driver_unsupported"}
    if not sender or len(sender) > 200:
        return {"ok": False, "dispatched": False, "error": "invalid_sender"}
    try:
        desktop, _ = container(config, request.get("profile"))
        state = load_state(request.get("profile"))
        target = state["conversations"].get(conversation) if isinstance(conversation, str) else None
        if not target:
            return {"ok": False, "dispatched": False, "error": "conversation_unknown"}
        name = target["name"]
        window_id, tree = open_client(desktop, driver)
        check_account(desktop, driver, request)
        tree = open_conversation(desktop, driver, window_id, tree, name, bool(target.get("folder")))
        _, draft = chat_input(driver, tree, name, loose=True)
        if collapse(draft):
            return {"ok": False, "dispatched": False, "error": "draft_present"}
        before_text, before_count = last_message(driver, tree)
        if driver == "wechat":
            spot = wechat_pat_target(desktop, window_id, tree, message_text)
            desktop.click(spot, button="right")
            time.sleep(0.5)
            x, y = pointer_at(desktop)
            # The menu opens at the pointer: "@ <name>" first, 拍一拍 second.
            item = {"x": x + 16, "y": y + 50, "w": 60, "h": 12}
        else:
            messages = find(tree, lambda n: n.get("name") == "消息列表")
            avatars = [n for n in walk(messages) if n.get("bounds") and n.get("role") in ("button", "image")
                       and n.get("name") == sender + "的头像"] if messages else []
            if not avatars:
                return {"ok": False, "dispatched": False, "error": "pat_target_not_visible"}
            desktop.click(avatars[-1]["bounds"], button="right")
            found = wait_for(lambda: next((n for n in walk(desktop.tree(window_id)) if n.get("bounds")
                                           and n.get("role") == "menu item" and text_of(n) == "拍一拍"), None), 2, every=0.1)
            if found is None:
                desktop.click({"x": avatars[-1]["bounds"]["x"] + 300, "y": avatars[-1]["bounds"]["y"], "w": 40, "h": 10})
                return {"ok": False, "dispatched": False, "error": "pat_menu_missing"}
            item = found["bounds"]
    except AdapterError as error:
        return {"ok": False, "dispatched": False, "error": str(error)}
    try:
        desktop.click(item)

        def noticed():
            last, count = last_message(driver, desktop.tree(window_id))
            return last if count != before_count or collapse(last) != collapse(before_text) else None
        notice = wait_for(noticed, 5, every=0.2)
        if notice and "拍了拍" in notice and sender[:6] in notice:
            now = int(time.time() * 1000)
            state["recent"].setdefault(conversation, []).append({"t": digest(collapse(notice)), "at": now})
            save_state(state)
            return {"ok": True, "receipt": "{}:{}:{}".format(conversation, digest(notice), now)}
        _, draft = chat_input(driver, desktop.tree(window_id), name, loose=True)
        if collapse(draft):
            # The click took the menu's other entry and left a mention in the input.
            clear_input(desktop)
    except AdapterError as error:
        print(str(error), file=sys.stderr)
    return {"ok": False, "error": "pat_unverified"}


def png_encode(rows, width, bpp):
    """An 8-bit PNG (RGB or RGBA) from raw rows, unfiltered."""
    def chunk(kind, data):
        return len(data).to_bytes(4, "big") + kind + data + (zlib.crc32(kind + data) & 0xffffffff).to_bytes(4, "big")
    header = width.to_bytes(4, "big") + len(rows).to_bytes(4, "big") + bytes([8, 6 if bpp == 4 else 2, 0, 0, 0])
    raw = b"".join(b"\x00" + row for row in rows)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def crop_window(desktop, window_id, bounds):
    """PNG bytes of the screen rectangle `bounds` inside the window, cut from a screenshot."""
    png, (left, top, scale) = desktop.screenshot(window_id)
    x0, y0 = max(0, int((bounds["x"] - left) * scale)), max(0, int((bounds["y"] - top) * scale))
    x1, y1 = int((bounds["x"] + bounds["w"] - left) * scale), int((bounds["y"] + bounds["h"] - top) * scale)
    rows, bpp = png_left_columns(png, x1)
    y1 = min(y1, len(rows))
    if x1 - x0 < 8 or y1 - y0 < 8:
        raise AdapterError("media_not_visible")
    return png_encode([row[x0 * bpp:x1 * bpp] for row in rows[y0:y1]], x1 - x0, bpp)


def stage_media(request, data, file_name, mime_type):
    """Writes fetched bytes under the runtime's media directory and returns the attachment entry for them."""
    directory = request.get("mediaDirectory")
    if not isinstance(directory, str) or not os.path.isdir(directory):
        raise AdapterError("media_directory_missing")
    if len(data) > int(request.get("maxMediaBytes") or 0):
        raise AdapterError("media_too_large")
    sha256 = hashlib.sha256(data).hexdigest()
    key = "fetch-{}-{}".format(sha256[:24], secrets.token_hex(4))
    descriptor, temporary = tempfile.mkstemp(prefix=".fetch-", dir=directory)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
    os.replace(temporary, os.path.join(directory, key))
    # The id goes into a URL path segment, where the runtime percent-encodes ":".
    return {"externalId": "fetch-{}-{}".format(request.get("profile"), sha256), "fileName": file_name,
            "mimeType": mime_type, "sizeBytes": len(data), "sha256": sha256, "stagingKey": key}


def media_nodes(driver, tree, kind, file_name):
    """On-screen message elements of `kind` in the open chat, oldest first."""
    if driver == "wechat":
        messages = find(tree, lambda n: n.get("role") == "list" and n.get("name") == "消息")
        items = [n for n in (messages.get("children") or []) if n.get("role") == "list item" and n.get("bounds")] \
            if messages else []
        if kind == "file":
            return [n for n in items if (n.get("name") or "").startswith("文件\n" + file_name + "\n")]
        found = []
        for item in items:
            if item.get("name") in ("图片", "动画表情"):
                image = find(item, lambda n: n is not item and n.get("role") == "image" and n.get("bounds"))
                found.append(image or item)
        return found
    messages = find(tree, lambda n: n.get("name") == "消息列表")
    if messages is None:
        return []
    if kind == "file":
        return [n for n in walk(messages) if n.get("role") == "paragraph" and n.get("bounds")
                and "".join(text_of(c) for c in walk(n) if c is not n) == file_name]
    return [n for n in walk(messages) if n.get("role") == "image" and n.get("bounds")
            and n["bounds"]["w"] >= 24 and n["bounds"]["h"] >= 24]


def save_file_as(desktop, driver, window_id, node, entry, file_name):
    """Saves a file message through its context menu's 另存为 into the outgoing folder; returns the host path."""
    host = os.path.expanduser(str(entry.get("outgoingDirectory") or ""))
    inside = str(entry.get("containerOutgoingDirectory") or "").rstrip("/")
    if not host or not os.path.isabs(host) or not inside.startswith("/"):
        raise AdapterError("attachments_unconfigured")
    folder = "fetch-" + secrets.token_hex(6)
    os.makedirs(os.path.join(host, folder), mode=0o777)
    os.chmod(os.path.join(host, folder), 0o777)
    bounds = node["bounds"]
    before = set(dialog_windows(desktop))
    desktop.click(bounds, button="right")
    time.sleep(0.8)
    # Only this exact item is ever clicked; the same menu holds 撤回 and 删除.
    save_item = desktop.control(window_id, r'menu item "另存为(\.\.\.|…)?"')
    if not save_item:
        desktop.park_pointer(window_id)
        desktop.click({"x": bounds["x"] + bounds["w"] / 2, "y": 18, "w": 0, "h": 0})
        raise AdapterError("save_menu_missing")
    desktop.press(save_item)
    dialog = None
    for _ in range(10):
        time.sleep(0.5)
        opened = [key for key in dialog_windows(desktop) if key not in before]
        if opened:
            dialog = opened[0]
            break
    if dialog is None:
        raise AdapterError("file_dialog_missing")
    target = "{}/{}/{}".format(inside, folder, file_name)
    field = None
    if driver == "wechat":
        field = desktop.control(dialog, r'text "文件名')
    else:
        desktop.activate(dialog)
    type_into(desktop, target, field, replace=True)
    desktop.key("Return")
    path = os.path.join(host, folder, file_name)
    previous = -1
    for _ in range(120):
        time.sleep(0.5)
        if dialog in dialog_windows(desktop) and _ == 10:
            desktop.tool("window", action="close", window=dialog)
            raise AdapterError("file_not_saved")
        if os.path.isfile(path):
            size = os.path.getsize(path)
            if size > 0 and size == previous:
                return path
            previous = size
    raise AdapterError("file_not_saved")


def fetch(request, config):
    """Fetches the last on-screen image, sticker or named file of a chat (opening it, which marks it read) and stages
    it for upload. Images and stickers are cut from a screenshot; files are saved through the client's 另存为."""
    driver, kind = request.get("driver"), request.get("kind")
    file_name = request.get("fileName") if isinstance(request.get("fileName"), str) else ""
    if driver not in APPS or kind not in ("image", "file") or (kind == "file" and not SAFE_FILE_NAME.match(file_name)):
        return {"ok": False, "error": "invalid_fetch"}
    try:
        desktop, entry = container(config, request.get("profile"))
        state = load_state(request.get("profile"))
        target = state["conversations"].get(request.get("conversationExternalId"))
        if not target:
            return {"ok": False, "error": "conversation_unknown"}
        window_id, tree = open_client(desktop, driver)
        check_account(desktop, driver, request)
        desktop.activate(window_id)
        tree = open_conversation(desktop, driver, window_id, tree, target["name"], bool(target.get("folder")))
        desktop.park_pointer(window_id)
        time.sleep(0.5)
        nodes = media_nodes(driver, desktop.tree(window_id), kind, file_name)
        if not nodes:
            return {"ok": False, "error": "media_not_visible"}
        if kind == "image":
            data, name, mime = crop_window(desktop, window_id, nodes[-1]["bounds"]), "image.png", "image/png"
        else:
            path = save_file_as(desktop, driver, window_id, nodes[-1], entry, file_name)
            with open(path, "rb") as handle:
                data = handle.read()
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)
            name, mime = file_name, "application/octet-stream"
        return {"ok": True, "attachment": stage_media(request, data, name, mime)}
    except AdapterError as error:
        return {"ok": False, "error": str(error)}
    except OSError:
        return {"ok": False, "error": "media_staging_failed"}


def handle(request):
    operation = request.get("op") if isinstance(request, dict) else None
    try:
        config = load_config()
    except AdapterError as error:
        if operation in ("send", "pat"):
            return {"ok": False, "dispatched": False, "error": str(error)}
        return {"ok": False, "sourceReadStatus": "failed", "error": str(error)}
    if operation == "send":
        return send(request, config)
    if operation == "pat":
        return pat(request, config)
    if operation == "fetch":
        return fetch(request, config)
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
