#!/usr/bin/env python3
"""Small direct HTTPS relay for a device-resident private adapter."""

import json
import hashlib
import http.client
import os
import re
import selectors
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request

from conversation_profiles import sync_profiles, sync_sender_avatars

if os.name == "posix":
    import fcntl

MAX_RESPONSE = 1024 * 1024
MAX_SCAN_RESPONSE = 900 * 1024
MAX_CURSOR_BYTES = 65_536
MAX_QQ_CONFIRMED_SEND_READS = 8
QQ_CONFIRMED_SEND_READ_ATTEMPTS = 3
MAX_EVENT = 256 * 1024
MAX_OUTBOX_BATCH_MESSAGES = 20
MAX_OUTBOX_BATCH_BYTES = MAX_SCAN_RESPONSE
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
MEDIA_CHUNK = 64 * 1024
MEDIA_UPLOAD_TIMEOUT = 600
STAGING_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,179}$")
IMAGE_MIME = re.compile(r"^image/[a-z0-9.+-]{1,100}$", re.IGNORECASE)
DEFAULT_OUTBOX_BYTES = 128 * 1024 * 1024
MAX_DELIVERIES_PER_PASS = 5
HEARTBEAT_MIN_INTERVAL = 30
ADAPTER_SCAN_TIMEOUT = 60
ADAPTER_SEND_TIMEOUT = 130
ADAPTER_WAKE_TIMEOUT = 55
AUTO_WAKE_INTERVAL = 60
SOURCE_RECOVERY_FAILURE_THRESHOLD = 3
SOURCE_RECOVERY_COOLDOWN = 300
SOURCE_STARTUP_SETTLE = 60
WAKE_REASON = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise urllib.error.HTTPError(request.full_url, code, "redirect_refused", headers, response)


class SourceReadError(RuntimeError):
    def __init__(self, code, *, attach_failure_pid=None, query_gate_pending_pid=None):
        super().__init__(code)
        self.attach_failure_pid = attach_failure_pid
        self.query_gate_pending_pid = query_gate_pending_pid


class SendPreDispatchError(RuntimeError):
    pass


def explicit_native_query_gate_pending(value):
    if type(value) is not dict or set(value) != {"stage", "errorCode", "dispatch", "processId"}:
        return False
    return (type(value["stage"]) is str and value["stage"] == "query_gate"
            and type(value["errorCode"]) is str and value["errorCode"] == "native-query-busy"
            and type(value["dispatch"]) is str and value["dispatch"] == "not_started"
            and type(value["processId"]) is int and value["processId"] > 1)


def explicit_native_attach_failure(value):
    if type(value) is not dict or set(value) != {"stage", "errorCode", "dispatch", "processId"}:
        return False
    return (type(value["stage"]) is str and value["stage"] == "attach"
            and type(value["errorCode"]) is str
            and value["errorCode"] in {"attach_failed", "timeout"}
            and type(value["dispatch"]) is str and value["dispatch"] == "not_started"
            and type(value["processId"]) is int and value["processId"] > 1)


def _event_route(message):
    default_trigger = "background" if message.get("conversationType") == "group" else "direct"
    background_group = (message.get("conversationType") == "group" and
                        message.get("trigger", default_trigger) == "background" and
                        message.get("isSelf") is not True)
    return "/api/connectors/group-text-backups" if background_group else "/api/connectors/events"


def _is_batchable_text(message):
    if not isinstance(message, dict):
        return False
    attachments = message.get("attachments", [])
    content_type = message.get("contentType")
    return (isinstance(message.get("body"), str)
            and bool(message["body"]) and attachments == []
            and content_type in (None, "", "text"))


def _is_late_attachment_enrichment(existing_body, incoming_body):
    try:
        existing = json.loads(existing_body)
        incoming = json.loads(incoming_body)
        if not isinstance(existing, dict) or not isinstance(incoming, dict):
            return False
        old_attachments = existing.get("attachments", [])
        new_attachments = incoming.get("attachments")
        if (old_attachments != []
                or not isinstance(new_attachments, list) or not new_attachments
                or existing.get("contentType") != "text"
                or incoming.get("contentType") != "mixed"):
            return False
        existing_immutable = {key: value for key, value in existing.items()
                              if key not in ("attachments", "contentType")}
        incoming_immutable = {key: value for key, value in incoming.items()
                              if key not in ("attachments", "contentType")}
        return (json.dumps(existing_immutable, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False)
                == json.dumps(incoming_immutable, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False, allow_nan=False))
    except (AttributeError, TypeError, ValueError):
        return False




def _ack_count(response, key, maximum):
    value = response.get(key)
    if type(value) is not int or value < 0 or value > maximum:
        raise RuntimeError("invalid_event_ack")
    return value


def open_database(path):
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        os.makedirs(parent, mode=0o700)
    db = sqlite3.connect(path, timeout=10)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA busy_timeout=10000")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS cursors(connector_id TEXT NOT NULL, profile TEXT NOT NULL,
        value TEXT NOT NULL, PRIMARY KEY(connector_id,profile));
      CREATE TABLE IF NOT EXISTS outbox(
        seq INTEGER PRIMARY KEY AUTOINCREMENT, connector_id TEXT NOT NULL, profile TEXT NOT NULL,
        external_id TEXT NOT NULL, body TEXT NOT NULL, size INTEGER NOT NULL,
        UNIQUE(connector_id, external_id));
      CREATE TABLE IF NOT EXISTS command_ledger(
        connector_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
        state TEXT NOT NULL,
        result TEXT, retryable INTEGER NOT NULL DEFAULT 0);
      CREATE UNIQUE INDEX IF NOT EXISTS command_ledger_key ON command_ledger(connector_id,idempotency_key);
      CREATE TABLE IF NOT EXISTS source_recovery(
        connector_id TEXT PRIMARY KEY, consecutive_failures INTEGER NOT NULL DEFAULT 0,
        last_success_at REAL NOT NULL DEFAULT 0, retry_after REAL NOT NULL DEFAULT 0,
        settle_until REAL NOT NULL DEFAULT 0);
    """)
    return db


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def verified_qq_external_id(profile, external_id, receipt_text):
    if not isinstance(profile, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", profile):
        return False
    if not isinstance(receipt_text, str) or len(receipt_text) > 8192:
        return False
    try:
        receipt = json.loads(receipt_text)
    except (TypeError, ValueError):
        return False
    if not isinstance(receipt, dict):
        return False
    source_id = receipt.get("sourceId")
    if not canonical_qq_source_id(source_id):
        return False
    value = 0x811C9DC5
    for byte in source_id.encode("ascii"):
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    alias = f"message-{value:08x}"
    return (receipt.get("messageAlias") == alias
            and type(receipt.get("messageType")) is int and receipt["messageType"] == 1
            and type(receipt.get("sendStatus")) is int and receipt["sendStatus"] == 2
            and receipt.get("confirmation") == "verified-status"
            and external_id == f"{profile}:qq-message:{source_id}")


def canonical_qq_source_id(value):
    if not isinstance(value, str) or len(value) > 20:
        return False
    if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value) is None or value == "-0":
        return False
    try:
        numeric = int(value)
    except ValueError:
        return False
    return -(1 << 63) <= numeric < (1 << 63)


def canonical_qq_owner_uin(value):
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value) is not None


def qq_directory_string(value, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value) or len(value) > 256:
        return False
    if value.strip() != value or any(ord(character) < 0x20 or ord(character) == 0x7F
                                     for character in value):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def qq_conversation_alias(value):
    digest = 0x811C9DC5
    encoded = value.encode("utf-16-le")
    for offset in range(0, len(encoded), 2):
        unit = encoded[offset] | (encoded[offset + 1] << 8)
        digest = ((digest ^ unit) * 0x01000193) & 0xFFFFFFFF
    return f"conversation-{digest:08x}"


def valid_qq_friend_directory(directory):
    if (not isinstance(directory, dict)
            or set(directory) != {"version", "ownerUin", "entries", "lastAttemptUin",
                                  "lastAttemptAt", "nextMainItem"}
            or directory.get("version") != "qfd1"
            or not canonical_qq_owner_uin(directory.get("ownerUin"))
            or not isinstance(directory.get("entries"), list)
            or len(directory["entries"]) > 100):
        return False
    last_uin = directory.get("lastAttemptUin")
    last_at = directory.get("lastAttemptAt")
    next_item = directory.get("nextMainItem")
    if last_uin is not None and not canonical_qq_owner_uin(last_uin):
        return False
    if (type(last_at) is not int or not 0 <= last_at <= 9007199254740991
            or (last_uin is None) != (last_at == 0)
            or type(next_item) is not int or not 0 <= next_item <= 512):
        return False
    seen_uins = set()
    seen_uids = set()
    seen_aliases = set()
    for entry in directory["entries"]:
        if (not isinstance(entry, dict) or set(entry) != {"peerUin", "peerUid", "guildId"}
                or not canonical_qq_owner_uin(entry.get("peerUin"))
                or not qq_directory_string(entry.get("peerUid"))
                or not qq_directory_string(entry.get("guildId"), allow_empty=True)):
            return False
        alias = qq_conversation_alias(entry["peerUid"])
        if (entry["peerUin"] in seen_uins or entry["peerUid"] in seen_uids
                or alias in seen_aliases):
            return False
        seen_uins.add(entry["peerUin"])
        seen_uids.add(entry["peerUid"])
        seen_aliases.add(alias)
    try:
        return len(compact(directory).encode("utf-8")) <= 16 * 1024
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return False


def qq_priority_owner_uin(cursor, profile):
    owners = []
    directory = cursor.get("qqFriendDirectory")
    if valid_qq_friend_directory(directory):
        owners.append(directory["ownerUin"])
    discovery = cursor.get("qqDiscoveryCache")
    discovery_size_ok = False
    if isinstance(discovery, list):
        try:
            discovery_size_ok = len(compact(discovery).encode("utf-8")) <= 24 * 1024
        except (TypeError, ValueError, UnicodeError, RecursionError):
            pass
    if (isinstance(discovery, list) and len(discovery) == 8
            and discovery[0] == "qdc3" and discovery[1] == profile
            and type(discovery[2]) is int and discovery[2] > 1
            and type(discovery[3]) is bool
            and type(discovery[4]) is int and 3600 <= discovery[4] <= 604800
            and type(discovery[5]) is int and 0 <= discovery[5] <= 9007199254740991
            and isinstance(discovery[7], list) and len(discovery[7]) <= 200
            and discovery_size_ok
            and canonical_qq_owner_uin(discovery[6])):
        owners.append(discovery[6])
    if not owners or len(set(owners)) != 1:
        return None
    return owners[0]


def valid_qq_confirmed_read_queue(value, owner_uin):
    if not isinstance(value, list) or len(value) > MAX_QQ_CONFIRMED_SEND_READS:
        return None
    expected = {"ownerUin", "alias", "sourceId", "remainingAttempts"}
    seen_aliases = set()
    queue_owner = owner_uin
    for entry in value:
        if (not isinstance(entry, dict) or set(entry) != expected
                or not canonical_qq_owner_uin(entry.get("ownerUin"))
                or (queue_owner is not None and entry.get("ownerUin") != queue_owner)
                or not isinstance(entry.get("alias"), str)
                or re.fullmatch(r"conversation-[a-f0-9]{8}", entry["alias"]) is None
                or entry["alias"] in seen_aliases
                or not canonical_qq_source_id(entry.get("sourceId"))
                or type(entry.get("remainingAttempts")) is not int
                or not 1 <= entry["remainingAttempts"] <= QQ_CONFIRMED_SEND_READ_ATTEMPTS):
            return None
        if queue_owner is None:
            queue_owner = entry["ownerUin"]
        seen_aliases.add(entry["alias"])
    return value


def qq_command_conversation_alias(profile, external_conversation_id):
    if not isinstance(profile, str) or not isinstance(external_conversation_id, str):
        return None
    prefix = profile + ":"
    if not external_conversation_id.startswith(prefix):
        return None
    alias = external_conversation_id[len(prefix):]
    if re.fullmatch(r"conversation-[a-f0-9]{8}", alias) is None:
        return None
    return alias


def resolve_local_paths(config, config_path):
    base = os.path.dirname(os.path.abspath(config_path))
    config.setdefault("mediaDirectory", config["database"] + ".media")
    for key in ("database", "adapter", "mediaDirectory"):
        if not os.path.isabs(config[key]):
            config[key] = os.path.join(base, config[key])
    return config


def run_adapter(path, request, timeout=30):
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, bufsize=0,
                                   start_new_session=(os.name == "posix"))
    except OSError:
        raise RuntimeError("adapter_spawn_failed") from None
    selector = None
    output = bytearray()
    try:
        selector = selectors.DefaultSelector()
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdin, selectors.EVENT_WRITE, "input")
        selector.register(process.stdout, selectors.EVENT_READ, "output")
        request_bytes = memoryview(compact(request).encode("utf-8"))
        offset = 0
        input_open = True
        output_open = True
        while input_open or output_open:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("adapter_timeout")
            for key, _ in selector.select(remaining):
                if key.data == "input":
                    try:
                        written = os.write(process.stdin.fileno(), request_bytes[offset:offset + 16384])
                        offset += written
                    except BrokenPipeError:
                        offset = len(request_bytes)
                    except BlockingIOError:
                        continue
                    if offset >= len(request_bytes):
                        selector.unregister(process.stdin)
                        process.stdin.close()
                        input_open = False
                else:
                    try:
                        chunk = os.read(process.stdout.fileno(), 16384)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(process.stdout)
                        output_open = False
                        continue
                    output.extend(chunk)
                    if len(output) > MAX_RESPONSE:
                        raise RuntimeError("adapter_response_too_large")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("adapter_timeout")
        return_code = process.wait(timeout=remaining)
        if return_code != 0:
            raise RuntimeError("adapter_failed")
        value = json.loads(bytes(output).decode("utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("adapter_invalid_response")
        return value
    except Exception:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                if process.poll() is None:
                    process.kill()
        elif process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        raise
    finally:
        if selector is not None:
            selector.close()
        if process.stdin:
            process.stdin.close()
        if process.stdout:
            process.stdout.close()


def adapter_timeout_for_request(request):
    operation = request.get("op") if isinstance(request, dict) else None
    if operation == "scan":
        return ADAPTER_SCAN_TIMEOUT
    if operation == "send":
        return ADAPTER_SEND_TIMEOUT
    if operation == "ensure-active":
        return ADAPTER_WAKE_TIMEOUT
    raise ValueError("unsupported_adapter_operation")


def wake_error_category(error):
    if isinstance(error, subprocess.TimeoutExpired):
        return "timeout"
    if isinstance(error, (json.JSONDecodeError, UnicodeDecodeError)):
        return "invalid_json"
    if isinstance(error, OSError):
        return "io_error"
    if isinstance(error, RuntimeError):
        return {
            "adapter_timeout": "timeout",
            "adapter_failed": "subprocess_failed",
            "adapter_invalid_response": "invalid_schema",
            "adapter_response_too_large": "response_too_large",
            "adapter_spawn_failed": "spawn_error",
        }.get(str(error), "adapter_error")
    return "adapter_error"


class Relay:
    def __init__(self, config, db=None, adapter_call=None, http_call=None):
        self.config = config
        self.db = db or open_database(config["database"])
        self.adapter_call = adapter_call or (
            lambda req: run_adapter(config["adapter"], req,
                                    timeout=adapter_timeout_for_request(req)))
        self.http_call = http_call or self.request
        self.base = config["serviceUrl"].rstrip("/")
        if not self.base.startswith("https://"):
            raise ValueError("https_required")
        self.connectors = config["connectors"]
        if "autoWake" in config and type(config["autoWake"]) is not bool:
            raise ValueError("invalid_auto_wake_configuration")
        self.media_directory = os.path.abspath(config.get("mediaDirectory", config["database"] + ".media"))
        if not os.path.isdir(self.media_directory):
            os.makedirs(self.media_directory, mode=0o700)
        try:
            os.chmod(self.media_directory, 0o700)
        except OSError:
            pass
        if not self.connectors or len({item["id"] for item in self.connectors}) != len(self.connectors):
            raise ValueError("invalid_connector_configuration")
        if len({item["token"] for item in self.connectors}) != len(self.connectors):
            raise ValueError("connector_tokens_must_be_unique")
        for connector in self.connectors:
            if (not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{7,199}", connector["id"]) or
                    len(connector["token"]) < 32):
                raise ValueError("invalid_connector_configuration")
        self.connector_by_id = {item["id"]: item for item in self.connectors}
        self.auto_wake = config.get("autoWake") is True
        if self.auto_wake and any(item.get("kind") != "qq" for item in self.connectors):
            raise ValueError("auto_wake_requires_qq_only")
        self.wake_ready = not self.auto_wake
        self.wake_readiness_established = not self.auto_wake
        self.last_wake_attempt = float("-inf")
        self.wake_ready_at = float("-inf")
        self.last_logged_wake_state = None
        self.wake_scan_pending = set()
        self.wake_scan_failures = {item["id"]: 0 for item in self.connectors}
        self.wake_scan_retry_at = {item["id"]: 0 for item in self.connectors}
        recovery_rows = {row[0]: row[1:] for row in self.db.execute(
            "SELECT connector_id,consecutive_failures,last_success_at,retry_after,settle_until FROM source_recovery")}
        self.source_failures = {item["id"]: recovery_rows.get(item["id"], (0, 0, 0))[0]
                                for item in self.connectors}
        self.attach_failure_streak = {item["id"]: (None, 0) for item in self.connectors}
        self.query_gate_failure_streak = {item["id"]: (None, 0) for item in self.connectors}
        self.source_last_success = {item["id"]: recovery_rows.get(item["id"], (0, 0, 0, 0))[1]
                                    for item in self.connectors}
        self.source_recovery_after = {item["id"]: recovery_rows.get(item["id"], (0, 0, 0, 0))[2]
                                      for item in self.connectors}
        self.source_settle_until = {item["id"]: recovery_rows.get(item["id"], (0, 0, 0, 0))[3]
                                    for item in self.connectors}
        self.source_state_durable = {item["id"]: True for item in self.connectors}
        self.connector = self.connectors[0]["id"]
        self.health = {item["id"]: False for item in self.connectors}
        self.last_scan = {item["id"]: float("-inf") for item in self.connectors}
        self.scan_interval = {item["id"]: 300 for item in self.connectors}
        self.registered = set()
        self.flush_next_index = 0
        self.failures = {item["id"]: 0 for item in self.connectors}
        self.retry_at = {item["id"]: 0 for item in self.connectors}
        self.heartbeat_failures = {item["id"]: 0 for item in self.connectors}
        self.heartbeat_retry_at = {item["id"]: 0 for item in self.connectors}
        self.heartbeat_last_state = {item["id"]: None for item in self.connectors}
        self.heartbeat_last_sent = {item["id"]: float("-inf") for item in self.connectors}

    def media_directory_for(self, connector_id):
        if not any(item["id"] == connector_id for item in self.connectors):
            raise RuntimeError("invalid_connector_media_directory")
        path = os.path.join(self.media_directory, connector_id)
        if os.path.commonpath([self.media_directory, os.path.abspath(path)]) != self.media_directory:
            raise RuntimeError("invalid_connector_media_directory")
        if not os.path.isdir(path):
            os.makedirs(path, mode=0o700, exist_ok=True)
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
        return path

    def eligible(self, connector_id):
        return time.monotonic() >= self.retry_at[connector_id]

    def failed(self, connector_id):
        count = self.failures[connector_id] + 1
        self.failures[connector_id] = count
        self.retry_at[connector_id] = time.monotonic() + min(15 * (2 ** min(count - 1, 5)), 300)

    def succeeded(self, connector_id):
        self.failures[connector_id] = 0
        self.retry_at[connector_id] = 0

    def persist_source_state(self, connector_id):
        try:
            self.db.execute(
                "INSERT INTO source_recovery(connector_id,consecutive_failures,last_success_at,retry_after,settle_until) "
                "VALUES(?,?,?,?,?) ON CONFLICT(connector_id) DO UPDATE SET "
                "consecutive_failures=excluded.consecutive_failures,last_success_at=excluded.last_success_at,"
                "retry_after=excluded.retry_after,settle_until=excluded.settle_until",
                (connector_id, self.source_failures[connector_id], self.source_last_success[connector_id],
                 self.source_recovery_after[connector_id], self.source_settle_until[connector_id]),
            )
            self.db.commit()
        except sqlite3.Error:
            self.source_state_durable[connector_id] = False
            try:
                self.db.rollback()
            except sqlite3.Error:
                pass
            return False
        self.source_state_durable[connector_id] = True
        return True

    def source_read_failed(self, connector_id, attach_failure_pid=None, query_gate_pending_pid=None):
        self.source_failures[connector_id] += 1
        current_pid, count = self.attach_failure_streak[connector_id]
        if self.auto_wake and type(attach_failure_pid) is int and attach_failure_pid > 1:
            self.attach_failure_streak[connector_id] = (
                attach_failure_pid, count + 1 if current_pid == attach_failure_pid else 1)
        else:
            self.attach_failure_streak[connector_id] = (None, 0)
        gate_pid, gate_count = self.query_gate_failure_streak[connector_id]
        if self.auto_wake and type(query_gate_pending_pid) is int and query_gate_pending_pid > 1:
            self.query_gate_failure_streak[connector_id] = (
                query_gate_pending_pid, gate_count + 1 if gate_pid == query_gate_pending_pid else 1)
        else:
            self.query_gate_failure_streak[connector_id] = (None, 0)
        return self.persist_source_state(connector_id)

    def source_read_succeeded(self, connector_id):
        self.source_failures[connector_id] = 0
        self.attach_failure_streak[connector_id] = (None, 0)
        self.query_gate_failure_streak[connector_id] = (None, 0)
        self.source_last_success[connector_id] = time.time()
        self.persist_source_state(connector_id)

    def recover_source_after_failures(self, connector_id):
        now = time.time()
        if (not self.auto_wake
                or not self.source_state_durable[connector_id]
                or self.source_failures[connector_id] < SOURCE_RECOVERY_FAILURE_THRESHOLD
                or now < self.source_recovery_after[connector_id]
                or now < self.source_settle_until[connector_id]):
            return False
        self.source_recovery_after[connector_id] = now + SOURCE_RECOVERY_COOLDOWN
        if not self.persist_source_state(connector_id):
            return False
        self.health[connector_id] = False
        try:
            result = self.ensure_active(recovery_driver=self.connector_by_id[connector_id].get("kind"))
        except Exception:
            return False
        return result

    def recover_attach_after_failures(self, connector_id):
        now = time.time()
        if (not self.auto_wake
                or not self.source_state_durable[connector_id]
                or self.attach_failure_streak[connector_id][1] < SOURCE_RECOVERY_FAILURE_THRESHOLD
                or now < self.source_recovery_after[connector_id]
                or now < self.source_settle_until[connector_id]):
            return False
        self.source_recovery_after[connector_id] = now + SOURCE_RECOVERY_COOLDOWN
        if not self.persist_source_state(connector_id):
            return False
        self.health[connector_id] = False
        try:
            return self.ensure_active(
                recovery_driver=self.connector_by_id[connector_id].get("kind"),
                recovery_reason="attach_failure",
                observed_pid=self.attach_failure_streak[connector_id][0],
            )
        except Exception:
            return False

    def recover_query_gate_after_failures(self, connector_id):
        now = time.time()
        streak = self.query_gate_failure_streak[connector_id]
        if (not self.auto_wake
                or not self.source_state_durable[connector_id]
                or streak[1] < SOURCE_RECOVERY_FAILURE_THRESHOLD
                or now < self.source_recovery_after[connector_id]
                or now < self.source_settle_until[connector_id]):
            return False
        self.source_recovery_after[connector_id] = now + SOURCE_RECOVERY_COOLDOWN
        self.query_gate_failure_streak[connector_id] = (None, 0)
        if not self.persist_source_state(connector_id):
            return False
        self.health[connector_id] = False
        try:
            return self.ensure_active(
                recovery_driver=self.connector_by_id[connector_id].get("kind"),
                recovery_reason="query_gate_pending",
                observed_pid=streak[0],
            )
        except Exception:
            return False

    def heartbeat_failed(self, connector_id):
        count = self.heartbeat_failures[connector_id] + 1
        self.heartbeat_failures[connector_id] = count
        self.heartbeat_retry_at[connector_id] = time.monotonic() + min(
            15 * (2 ** min(count - 1, 2)), 60)

    def heartbeat_succeeded(self, connector_id):
        self.heartbeat_failures[connector_id] = 0
        self.heartbeat_retry_at[connector_id] = 0

    def send_heartbeat(self, connector_id, state):
        now = time.monotonic()
        if now < self.heartbeat_retry_at[connector_id]:
            return False
        if (self.heartbeat_last_state[connector_id] == state and
                now - self.heartbeat_last_sent[connector_id] < HEARTBEAT_MIN_INTERVAL):
            return False
        self.select_connector(self.connector_by_id[connector_id])
        try:
            self.http_call("POST", "/api/connectors/heartbeat", {
                "connectorId": connector_id,
                "state": state})
        except Exception:
            self.heartbeat_failed(connector_id)
            return False
        self.heartbeat_succeeded(connector_id)
        self.heartbeat_last_state[connector_id] = state
        self.heartbeat_last_sent[connector_id] = time.monotonic()
        return True

    def select_connector(self, connector):
        self.connector = connector["id"]
        self.active_connector = connector

    def headers(self):
        return {"Authorization": "Bearer " + self.active_connector["token"],
                "x-connector-id": self.connector,
                "User-Agent": "MessageCenterDevice/1.0",
                "Accept": "application/json"}

    def request(self, method, path, payload=None):
        data = None if payload is None else compact(payload).encode("utf-8")
        headers = self.headers()
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(req, timeout=20) as response:
            if response.geturl() != req.full_url:
                raise RuntimeError("redirect_refused")
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise RuntimeError("response_too_large")
            value = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(value, dict) or value.get("ok") is False:
                raise RuntimeError(str(value.get("error", "invalid_response")))
            return value

    def count_bytes(self, connector_id=None):
        if connector_id is None:
            row = self.db.execute("SELECT COALESCE(SUM(size),0) FROM outbox").fetchone()
        else:
            row = self.db.execute("SELECT COALESCE(SUM(size),0) FROM outbox WHERE connector_id=?",
                                  (connector_id,)).fetchone()
        return int(row[0])

    def cleanup_unreferenced_media(self):
        for connector in self.connectors:
            connector_id = connector["id"]
            referenced = set()
            try:
                for (body,) in self.db.execute("SELECT body FROM outbox WHERE connector_id=?", (connector_id,)):
                    for attachment in json.loads(body).get("attachments", []):
                        key = attachment.get("stagingKey")
                        if isinstance(key, str) and STAGING_KEY.fullmatch(key):
                            referenced.add(key)
            except (ValueError, TypeError, AttributeError):
                continue
            try:
                with os.scandir(self.media_directory_for(connector_id)) as entries:
                    for entry in entries:
                        if entry.name not in referenced and not entry.is_dir(follow_symlinks=False):
                            try:
                                os.unlink(entry.path)
                            except OSError:
                                pass
            except OSError:
                pass

    def _outbox_prefix(self, connector_id, first_row):
        rows = self.db.execute(
            "SELECT seq,profile,external_id,body,size FROM outbox "
            "WHERE connector_id=? ORDER BY seq LIMIT ?",
            (connector_id, MAX_OUTBOX_BATCH_MESSAGES),
        ).fetchall()
        if not rows or rows[0] != first_row:
            raise RuntimeError("outbox_head_changed")
        try:
            first_message = json.loads(first_row[3])
        except (TypeError, ValueError):
            return [first_row], [None]
        if not _is_batchable_text(first_message):
            return [first_row], [first_message]
        selected_rows = [first_row]
        selected_messages = [first_message]
        route = _event_route(first_message)
        payload = {"connectorId": connector_id, "messages": selected_messages}
        if len(compact(payload).encode("utf-8")) > MAX_OUTBOX_BATCH_BYTES:
            raise RuntimeError("outbox_batch_payload_too_large")
        for row in rows[1:]:
            if row[1] != first_row[1]:
                break
            try:
                message = json.loads(row[3])
            except (TypeError, ValueError):
                break
            if not _is_batchable_text(message) or _event_route(message) != route:
                break
            candidate_messages = selected_messages + [message]
            candidate_payload = {"connectorId": connector_id, "messages": candidate_messages}
            if len(compact(candidate_payload).encode("utf-8")) > MAX_OUTBOX_BATCH_BYTES:
                break
            selected_rows.append(row)
            selected_messages.append(message)
        return selected_rows, selected_messages

    def _validate_event_ack(self, path, response, expected_count):
        if not isinstance(response, dict) or response.get("ok") is not True:
            raise RuntimeError("event_not_acknowledged")
        if _ack_count(response, "received", expected_count) != expected_count:
            raise RuntimeError("event_not_acknowledged")
        if path == "/api/connectors/events":
            _ack_count(response, "inserted", expected_count)
            _ack_count(response, "upgraded", expected_count)
            _ack_count(response, "promoted", expected_count)
            if _ack_count(response, "suppressed", expected_count) != 0:
                raise RuntimeError("event_not_acknowledged")
        elif path == "/api/connectors/group-text-backups":
            _ack_count(response, "inserted", expected_count)
            _ack_count(response, "normalizedInserted", expected_count)
            if type(response.get("retentionDays")) is not int or response["retentionDays"] != 30:
                raise RuntimeError("event_not_acknowledged")
        else:
            raise RuntimeError("event_route_unavailable")

    def _delete_outbox_prefix(self, connector_id, rows):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for seq, profile, external_id, body, size in rows:
                cursor = self.db.execute(
                    "DELETE FROM outbox WHERE seq=? AND connector_id=? AND profile=? "
                    "AND external_id=? AND body=? AND size=?",
                    (seq, connector_id, profile, external_id, body, size),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("outbox_prefix_changed")
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def scan_profile(self, profile, history=False):
        ceiling = max(1, int(self.config.get("outboxMaxBytes", DEFAULT_OUTBOX_BYTES)) // len(self.connectors))
        if self.count_bytes(self.connector) >= ceiling:
            return None
        row = self.db.execute("SELECT value FROM cursors WHERE connector_id=? AND profile=?",
                              (self.connector, profile)).fetchone()
        cursor = json.loads(row[0]) if row else None
        limit = max(1, min(int(self.config.get("pageLimit", 20)), 20))
        remaining = max(0, ceiling - self.count_bytes(self.connector))
        connector = self.connector_by_id[self.connector]
        driver = connector.get("kind")
        if driver not in {"qq", "wechat"}:
            raise RuntimeError("unsupported_connector_driver")
        try:
            result = self.adapter_call({"op": "scan", "driver": driver,
                                        "profile": profile, "cursor": cursor,
                                        "limit": limit, "maxBytes": MAX_SCAN_RESPONSE,
                                        "maxEventBytes": MAX_EVENT, "mediaDirectory": self.media_directory_for(self.connector),
                                        "maxMediaBytes": remaining, "history": bool(history)})
        except Exception as error:
            raise SourceReadError("source_read_failed") from error
        if not isinstance(result, dict):
            raise RuntimeError("invalid_scan_result")
        source_read_ok = result.get("sourceReadOk")
        if type(source_read_ok) is not bool:
            raise RuntimeError("invalid_scan_result")
        if source_read_ok is False:
            failure = result.get("nativeFailure")
            raise SourceReadError(
                "source_read_failed",
                attach_failure_pid=(failure["processId"]
                                    if explicit_native_attach_failure(failure) else None),
                query_gate_pending_pid=(failure["processId"]
                                        if explicit_native_query_gate_pending(failure) else None),
            )
        if (result.get("ok") is not True or "cursor" not in result or
                not isinstance(result.get("messages"), list)):
            raise RuntimeError("invalid_scan_result")
        health = result.get("health")
        if not isinstance(health, str) or health not in {"online", "degraded"}:
            raise RuntimeError("invalid_scan_health")
        if len(compact(result).encode("utf-8")) > MAX_SCAN_RESPONSE:
            raise RuntimeError("scan_response_too_large")
        messages = result["messages"]
        if len(messages) > limit:
            raise RuntimeError("scan_page_too_large")
        encoded = []
        staged_bytes = 0
        page_ids = {}
        for message in messages:
            if (not isinstance(message, dict) or not isinstance(message.get("externalId"), str) or
                    not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{0,199}", message["externalId"])):
                raise RuntimeError("invalid_event")
            if (not isinstance(message.get("conversationExternalId"), str) or not message["conversationExternalId"] or
                    not isinstance(message.get("conversationTitle"), str) or not message["conversationTitle"] or
                    not isinstance(message.get("senderName"), str) or not message["senderName"] or
                    not isinstance(message.get("occurredAt"), str) or
                    not isinstance(message.get("body", ""), str) or
                    not isinstance(message.get("context", []), list) or len(message.get("context", [])) > 20):
                raise RuntimeError("invalid_event")
            try:
                datetime.fromisoformat(message["occurredAt"].replace("Z", "+00:00"))
            except ValueError:
                raise RuntimeError("invalid_event_time")
            conversation_type = message.get("conversationType", "direct")
            trigger = message.get("trigger", "direct" if conversation_type != "group" else "background")
            if conversation_type not in ("direct", "group"):
                raise RuntimeError("invalid_event")
            if trigger not in (("mention", "explicit_request", "background") if conversation_type == "group" else ("direct",)):
                raise RuntimeError("invalid_event")
            if "isSelf" in message and type(message["isSelf"]) is not bool:
                raise RuntimeError("invalid_event")
            attachments = message.get("attachments", [])
            if attachments is None:
                attachments = []
            if not isinstance(attachments, list) or len(attachments) > 20:
                raise RuntimeError("invalid_attachments")
            normalized_attachments = []
            for attachment in attachments:
                normalized_attachments.append(self.validate_staged_attachment(attachment))
            if conversation_type == "group" and trigger == "background" and message.get("isSelf") is not True:
                body = message.get("body", "")
                if not body.strip() and normalized_attachments:
                    message["body"] = "[图片]"
                    body = message["body"]
                try:
                    body_length = len(body.encode("utf-16-le")) // 2
                except UnicodeEncodeError:
                    raise RuntimeError("invalid_group_text_backup")
                if (not body.strip() or body_length > 20000):
                    raise RuntimeError("invalid_group_text_backup")
            if normalized_attachments:
                message["attachments"] = normalized_attachments
            media_size = sum(item["sizeBytes"] for item in normalized_attachments)
            for context_item in message.get("context", []):
                if not isinstance(context_item, dict) or not isinstance(context_item.get("receivedAt"), str):
                    raise RuntimeError("invalid_event_context")
                try:
                    datetime.fromisoformat(context_item["receivedAt"].replace("Z", "+00:00"))
                except ValueError:
                    raise RuntimeError("invalid_event_context")
            if message.get("observedAt") is not None:
                if not isinstance(message["observedAt"], str):
                    raise RuntimeError("invalid_event")
                try:
                    datetime.fromisoformat(message["observedAt"].replace("Z", "+00:00"))
                except ValueError:
                    raise RuntimeError("invalid_event")
            raw = compact({"connectorId": self.connector, "messages": [message]}).encode("utf-8")
            if len(raw) > MAX_EVENT:
                raise RuntimeError("event_too_large")
            body = compact(message)
            previous = page_ids.get(message["externalId"])
            if previous is not None and previous != body:
                raise RuntimeError("event_id_conflict_in_page")
            if previous is None:
                staged_bytes += media_size
                if staged_bytes > remaining:
                    raise RuntimeError("media_budget_exceeded")
                page_ids[message["externalId"]] = body
                encoded.append((self.connector, profile, str(message["externalId"]), body,
                                len(raw) + media_size))
        candidate = compact(result.get("cursor"))
        if len(candidate.encode("utf-8")) > MAX_CURSOR_BYTES:
            raise RuntimeError("cursor_too_large")
        sync_profiles(self, result.get("conversationProfiles", []))
        sync_sender_avatars(self, result.get("senderAvatars", []))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            current = self.count_bytes(self.connector)
            capacity_delta = 0
            inserts = []
            enrichments = []
            for item in encoded:
                existing = self.db.execute(
                    "SELECT seq,profile,body,size FROM outbox WHERE connector_id=? AND external_id=?",
                    (item[0], item[2]),
                ).fetchone()
                if existing is None:
                    inserts.append(item)
                    capacity_delta += item[4]
                    continue
                if existing[1] != item[1]:
                    raise RuntimeError("event_id_conflict_in_outbox")
                if existing[2] == item[3]:
                    continue
                if not _is_late_attachment_enrichment(existing[2], item[3]):
                    raise RuntimeError("event_id_conflict_in_outbox")
                enrichments.append((existing[0], item[0], item[1], item[2],
                                    existing[2], existing[3], item[3], item[4]))
                capacity_delta += item[4] - existing[3]
            ceiling = max(1, int(self.config.get("outboxMaxBytes", DEFAULT_OUTBOX_BYTES)) // len(self.connectors))
            if current + capacity_delta > ceiling:
                self.db.rollback()
                return None
            for item in inserts:
                self.db.execute("INSERT OR IGNORE INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,?)", item)
            for seq, connector_id, profile, external_id, old_body, old_size, new_body, new_size in enrichments:
                updated = self.db.execute(
                    "UPDATE outbox SET body=?,size=? WHERE seq=? AND connector_id=? AND profile=? "
                    "AND external_id=? AND body=? AND size=?",
                    (new_body, new_size, seq, connector_id, profile, external_id, old_body, old_size),
                )
                if updated.rowcount != 1:
                    raise RuntimeError("outbox_prefix_changed")
            self.db.execute("INSERT INTO cursors(connector_id,profile,value) VALUES(?,?,?) "
                            "ON CONFLICT(connector_id,profile) DO UPDATE SET value=excluded.value",
                            (self.connector, profile, candidate))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        active = result.get("active") is True
        self.scan_interval[self.connector] = 15 if result.get("more") is True else (60 if active else 300)
        self.source_read_succeeded(self.connector)
        return result.get("health") == "online"

    def ensure_active(self, recovery_driver=None, recovery_reason="read_failure", observed_pid=None):
        if not self.auto_wake:
            return True
        now = time.monotonic()
        if (recovery_driver is None and now - self.last_wake_attempt < AUTO_WAKE_INTERVAL):
            return self.wake_readiness_current()
        self.last_wake_attempt = now
        was_ready = self.wake_ready
        self.wake_ready = False
        try:
            request = {"op": "ensure-active", "driver": "qq"}
            if recovery_driver is not None:
                if (recovery_driver != "qq"
                        or recovery_reason not in {"read_failure", "attach_failure", "query_gate_pending"}
                        or (recovery_reason in {"attach_failure", "query_gate_pending"}
                            and (type(observed_pid) is not int or observed_pid <= 1))):
                    raise RuntimeError("invalid_recovery_driver")
                request.update({"reason": recovery_reason, "driver": recovery_driver})
                if recovery_reason in {"attach_failure", "query_gate_pending"}:
                    request["observedPid"] = observed_pid
            result = self.adapter_call(request)
            if (not isinstance(result, dict) or set(result) != {"ok", "ready", "attempted", "reason"} or
                    result.get("ok") is not True or type(result.get("ready")) is not bool or
                    type(result.get("attempted")) is not bool or
                    (result["ready"] and result["attempted"]) or
                    not isinstance(result.get("reason"), str) or not WAKE_REASON.fullmatch(result["reason"])):
                self.wake_ready = False
                self.log_wake_state(False, False, "invalid_schema")
                return False
            self.wake_ready = result["ready"]
            self.wake_ready_at = time.monotonic()
            if self.wake_ready and not was_ready:
                self.wake_scan_pending = set(self.connector_by_id)
                if not self.wake_readiness_established:
                    self.wake_readiness_established = True
                    settle_until = time.time() + SOURCE_STARTUP_SETTLE
                    for connector_id in self.connector_by_id:
                        self.health[connector_id] = False
                        self.source_settle_until[connector_id] = settle_until
                        self.persist_source_state(connector_id)
            if result["attempted"]:
                settle_until = time.time() + SOURCE_STARTUP_SETTLE
                for connector_id in self.connector_by_id:
                    self.health[connector_id] = False
                    self.source_settle_until[connector_id] = settle_until
                    self.persist_source_state(connector_id)
            self.log_wake_state(result["ready"], result["attempted"], result["reason"])
            return self.wake_readiness_current()
        except Exception as error:
            self.wake_ready = False
            self.log_wake_state(False, False, wake_error_category(error))
            return False

    def log_wake_state(self, ready, attempted, reason):
        state = (ready, attempted, reason)
        if state == self.last_logged_wake_state:
            return
        self.last_logged_wake_state = state
        observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        sys.stderr.write(compact({"observedAt": observed_at, "ready": ready,
                                  "attempted": attempted, "reason": reason}) + "\n")
        sys.stderr.flush()

    def wake_readiness_current(self):
        return (not self.auto_wake or
                (self.wake_ready and time.monotonic() - self.wake_ready_at < AUTO_WAKE_INTERVAL))

    def wake_scan_failed(self, connector_id):
        count = self.wake_scan_failures[connector_id] + 1
        self.wake_scan_failures[connector_id] = count
        self.wake_scan_retry_at[connector_id] = time.monotonic() + min(15 * (2 ** min(count - 1, 5)), 300)

    def wake_scan_succeeded(self, connector_id):
        self.wake_scan_failures[connector_id] = 0
        self.wake_scan_retry_at[connector_id] = 0

    def validate_staged_attachment(self, attachment):
        if not isinstance(attachment, dict):
            raise RuntimeError("invalid_attachment")
        key = attachment.get("stagingKey")
        if not isinstance(key, str) or not STAGING_KEY.fullmatch(key):
            raise RuntimeError("invalid_staging_key")
        external_id = attachment.get("externalId")
        file_name = attachment.get("fileName")
        mime_type = attachment.get("mimeType")
        size = attachment.get("sizeBytes")
        expected_hash = attachment.get("sha256")
        if (not isinstance(external_id, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{0,199}", external_id) or
                not isinstance(file_name, str) or not file_name or len(file_name) > 255 or
                any(ord(character) < 32 or ord(character) == 127 for character in file_name) or
                not isinstance(mime_type, str) or not IMAGE_MIME.fullmatch(mime_type) or
                not isinstance(size, int) or isinstance(size, bool) or size < 1 or size > MAX_ATTACHMENT_BYTES or
                not isinstance(expected_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_hash)):
            raise RuntimeError("invalid_attachment_metadata")
        media_directory = self.media_directory_for(self.connector)
        path = os.path.join(media_directory, key)
        if os.path.commonpath([media_directory, os.path.abspath(path)]) != media_directory:
            raise RuntimeError("invalid_staging_key")
        if os.path.islink(path) or not os.path.isfile(path):
            raise RuntimeError("staged_file_missing")
        digest = hashlib.sha256()
        observed = 0
        with open(path, "rb") as source:
            while True:
                chunk = source.read(MEDIA_CHUNK)
                if not chunk:
                    break
                observed += len(chunk)
                if observed > size or observed > MAX_ATTACHMENT_BYTES:
                    raise RuntimeError("staged_file_size_mismatch")
                digest.update(chunk)
        if observed != size or digest.hexdigest() != expected_hash:
            raise RuntimeError("staged_file_integrity_mismatch")
        return {"externalId": external_id, "fileName": file_name,
                "mimeType": mime_type, "sizeBytes": size, "sha256": expected_hash,
                "stagingKey": key}

    def upload_attachment(self, message, attachment):
        parsed = urllib.parse.urlsplit(self.base)
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError("https_required")
        file_id = attachment["externalId"]
        path = os.path.join(self.media_directory_for(self.connector), attachment["stagingKey"])
        target = "/api/connectors/files/" + urllib.parse.quote(file_id, safe="")
        connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=30)
        deadline = time.monotonic() + MEDIA_UPLOAD_TIMEOUT
        headers = dict(self.headers())
        headers.update({"Content-Type": attachment["mimeType"],
                        "Content-Length": str(attachment["sizeBytes"]),
                        "x-conversation-id": str(message["conversationExternalId"]),
                        "x-file-external-id": file_id,
                        "x-file-name": urllib.parse.quote(attachment["fileName"], safe=""),
                        "x-content-sha256": attachment["sha256"]})
        try:
            connection.putrequest("PUT", target)
            for name, value in headers.items():
                connection.putheader(name, value)
            connection.endheaders()
            with open(path, "rb") as source:
                while True:
                    chunk = source.read(MEDIA_CHUNK)
                    if not chunk:
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError("attachment_upload_timeout")
                    sock = getattr(connection, "sock", None)
                    if sock:
                        sock.settimeout(min(30, remaining))
                    connection.send(chunk)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("attachment_upload_timeout")
            sock = getattr(connection, "sock", None)
            if sock:
                sock.settimeout(min(30, remaining))
            response = connection.getresponse()
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE or response.status < 200 or response.status >= 300:
                raise RuntimeError("attachment_upload_failed")
            value = json.loads(raw.decode("utf-8")) if raw else {}
            if value.get("ok") is not True:
                raise RuntimeError("attachment_upload_failed")
            return value
        finally:
            connection.close()

    def flush_one(self):
        count = len(self.connectors)
        order = [(self.flush_next_index + offset) % count for offset in range(count)]
        for index in order:
            connector = self.connectors[index]
            connector_id = connector["id"]
            if not self.eligible(connector_id):
                continue
            row = self.db.execute("SELECT seq,profile,external_id,body,size FROM outbox "
                                  "WHERE connector_id=? ORDER BY seq LIMIT 1",
                                  (connector_id,)).fetchone()
            if row is None:
                continue
            try:
                profile = row[1]
                self.select_connector(connector)
                rows, messages = self._outbox_prefix(connector_id, row)
                message = messages[0]
                attachments = message.get("attachments", [])
                for attachment in attachments:
                    self.upload_attachment(message, attachment)
                if attachments:
                    message["attachments"] = [{key: value for key, value in attachment.items()
                                               if key != "stagingKey"} for attachment in attachments]
                path = _event_route(message)
                response = self.http_call("POST", path,
                                          {"connectorId": connector_id, "messages": messages})
                self._validate_event_ack(path, response, len(rows))
            except Exception:
                self.failed(connector_id)
                continue
            self._delete_outbox_prefix(connector_id, rows)
            for attachment in attachments:
                try:
                    os.remove(os.path.join(self.media_directory_for(connector_id), attachment["stagingKey"]))
                except OSError:
                    pass
            self.succeeded(connector_id)
            self.flush_next_index = (index + 1) % count
            return connector_id
        return None

    def complete(self, command, result):
        self.http_call("POST", "/api/connectors/commands/" + urllib.parse.quote(command["id"], safe="") + "/complete",
                       {"connectorId": self.connector, "leaseToken": command["leaseToken"], **result})

    def qq_send_cursor(self, connector, profile):
        if (not isinstance(connector, dict) or connector.get("id") != self.connector
                or connector.get("kind") != "qq" or connector.get("profile") != profile
                or not isinstance(profile, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", profile)):
            raise SendPreDispatchError("qq_send_scope_mismatch")
        try:
            row = self.db.execute(
                "SELECT value FROM cursors WHERE connector_id=? AND profile=?",
                (self.connector, profile),
            ).fetchone()
        except sqlite3.Error:
            raise SendPreDispatchError("qq_send_cursor_unavailable") from None
        if row is None:
            raise SendPreDispatchError("qq_send_cursor_unavailable")
        try:
            raw_cursor = row[0]
            if not isinstance(raw_cursor, str) or len(raw_cursor.encode("utf-8")) > MAX_CURSOR_BYTES:
                raise SendPreDispatchError("qq_send_cursor_oversized")
            cursor = json.loads(raw_cursor)
            encoded_size = len(compact(cursor).encode("utf-8"))
        except SendPreDispatchError:
            raise
        except (TypeError, ValueError, UnicodeError):
            raise SendPreDispatchError("qq_send_cursor_invalid") from None
        if (not isinstance(cursor, dict) or cursor.get("version") != 1
                or not isinstance(cursor.get("conversations"), dict)):
            raise SendPreDispatchError("qq_send_cursor_invalid")
        if encoded_size > MAX_CURSOR_BYTES:
            raise SendPreDispatchError("qq_send_cursor_oversized")
        return cursor

    def _register_qq_confirmed_read(self, profile, alias, source_id):
        connector = self.connector_by_id.get(self.connector, {})
        if (connector.get("kind") != "qq" or connector.get("profile") != profile
                or not isinstance(profile, str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", profile)
                or not isinstance(alias, str)
                or re.fullmatch(r"conversation-[a-f0-9]{8}", alias) is None
                or not canonical_qq_source_id(source_id)):
            return
        savepoint_started = False
        try:
            self.db.execute("SAVEPOINT qq_confirmed_read")
            savepoint_started = True
            row = self.db.execute(
                "SELECT value FROM cursors WHERE connector_id=? AND profile=?",
                (self.connector, profile),
            ).fetchone()
            if row is None or not isinstance(row[0], str):
                self.db.execute("RELEASE qq_confirmed_read")
                return
            raw_cursor = row[0]
            if len(raw_cursor.encode("utf-8")) > MAX_CURSOR_BYTES:
                self.db.execute("RELEASE qq_confirmed_read")
                return
            try:
                cursor = json.loads(raw_cursor)
            except (TypeError, ValueError, UnicodeError):
                self.db.execute("RELEASE qq_confirmed_read")
                return
            if (not isinstance(cursor, dict) or type(cursor.get("version")) is not int
                    or cursor.get("version") != 1
                    or not isinstance(cursor.get("conversations"), dict)):
                self.db.execute("RELEASE qq_confirmed_read")
                return
            owner_uin = qq_priority_owner_uin(cursor, profile)
            original_queue = cursor.get("qqConfirmedSendReads")
            queue_was_present = "qqConfirmedSendReads" in cursor
            queue = valid_qq_confirmed_read_queue(original_queue, owner_uin)
            malformed_queue = queue_was_present and queue is None
            if owner_uin is None:
                if malformed_queue:
                    candidate_cursor = dict(cursor)
                    candidate_cursor.pop("qqConfirmedSendReads", None)
                    updated_value = compact(candidate_cursor)
                    if len(updated_value.encode("utf-8")) <= MAX_CURSOR_BYTES:
                        self.db.execute(
                            "UPDATE cursors SET value=? WHERE connector_id=? AND profile=? AND value=?",
                            (updated_value, self.connector, profile, raw_cursor),
                        )
                self.db.execute("RELEASE qq_confirmed_read")
                return
            if queue is None:
                queue = []
            replacement = {"ownerUin": owner_uin, "alias": alias,
                           "sourceId": source_id,
                           "remainingAttempts": QQ_CONFIRMED_SEND_READ_ATTEMPTS}
            existing_index = next((index for index, entry in enumerate(queue)
                                   if entry["alias"] == alias), None)
            if existing_index is None:
                if len(queue) >= MAX_QQ_CONFIRMED_SEND_READS:
                    queue.pop(0)
                queue.append(replacement)
            else:
                queue[existing_index] = replacement
            candidate_cursor = dict(cursor)
            candidate_cursor["qqConfirmedSendReads"] = queue
            candidate = compact(candidate_cursor)
            if len(candidate.encode("utf-8")) <= MAX_CURSOR_BYTES:
                updated_value = candidate
            elif malformed_queue:
                candidate_cursor = dict(cursor)
                candidate_cursor.pop("qqConfirmedSendReads", None)
                updated_value = compact(candidate_cursor)
                if len(updated_value.encode("utf-8")) > MAX_CURSOR_BYTES:
                    self.db.execute("RELEASE qq_confirmed_read")
                    return
            else:
                self.db.execute("RELEASE qq_confirmed_read")
                return
            self.db.execute(
                "UPDATE cursors SET value=? WHERE connector_id=? AND profile=? AND value=?",
                (updated_value, self.connector, profile, raw_cursor),
            )
            self.db.execute("RELEASE qq_confirmed_read")
        except sqlite3.Error:
            if savepoint_started:
                try:
                    self.db.execute("ROLLBACK TO qq_confirmed_read")
                    self.db.execute("RELEASE qq_confirmed_read")
                except sqlite3.Error:
                    pass
        except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
            if savepoint_started:
                try:
                    self.db.execute("ROLLBACK TO qq_confirmed_read")
                    self.db.execute("RELEASE qq_confirmed_read")
                except sqlite3.Error:
                    pass

    def process_command(self, command, profile):
        key = command.get("idempotencyKey")
        if not key:
            self.complete(command, {"ok": False, "error": "invalid_idempotency_key"})
            return
        payload = command.get("payload") or {}
        fingerprint = hashlib.sha256(compact({
            "externalConversationId": payload.get("externalConversationId"),
            "body": payload.get("body", ""), "attachments": payload.get("attachments", []),
        }).encode("utf-8")).hexdigest()
        row = self.db.execute("SELECT state,result,retryable,fingerprint FROM command_ledger WHERE connector_id=? AND idempotency_key=?",
                              (self.connector, key)).fetchone()
        if row:
            if row[3] != fingerprint:
                self.complete(command, {"uncertain": True, "error": "device_idempotency_key_conflict"})
                return
            if row[0] == "done":
                outcome = json.loads(row[1])
                self.complete(command, outcome)
                return
            if row[0] == "started":
                outcome = {"uncertain": True, "error": "device_send_outcome_uncertain"}
                self.complete(command, outcome)
                return
            try:
                self.http_call("POST", "/api/connectors/commands/" +
                               urllib.parse.quote(command["id"], safe="") + "/lease",
                               {"connectorId": self.connector, "leaseToken": command["leaseToken"]})
            except Exception:
                return False
            self.db.execute("UPDATE command_ledger SET state='started',result=NULL WHERE connector_id=? AND idempotency_key=?",
                            (self.connector, key))
            self.db.commit()
        else:
            try:
                self.http_call("POST", "/api/connectors/commands/" +
                               urllib.parse.quote(command["id"], safe="") + "/lease",
                               {"connectorId": self.connector, "leaseToken": command["leaseToken"]})
            except Exception:
                return False
            self.db.execute("INSERT INTO command_ledger(connector_id,idempotency_key,fingerprint,state) "
                            "VALUES(?,?,?,'started')", (self.connector, key, fingerprint))
            self.db.commit()
        if payload.get("attachments"):
            outcome, retryable = {"ok": False, "error": "adapter_file_send_not_supported"}, 0
            self.db.execute("UPDATE command_ledger SET state='done',result=? WHERE connector_id=? AND idempotency_key=?",
                            (compact(outcome), self.connector, key))
            self.db.commit()
            self.complete(command, outcome)
            return
        if not self.wake_readiness_current():
            self.db.execute("UPDATE command_ledger SET state='retry',retryable=1 WHERE connector_id=? AND idempotency_key=?",
                            (self.connector, key))
            self.db.commit()
            self.complete(command, {"retry": True, "error": "device_not_ready"})
            return
        priority_read = None
        try:
            connector = self.connector_by_id[self.connector]
            driver = connector.get("kind")
            if driver not in {"qq", "wechat"}:
                raise RuntimeError("unsupported_connector_driver")
            request = {"op": "send", "driver": driver,
                       "profile": profile, "commandId": command["id"],
                       "idempotencyKey": key,
                       "conversationExternalId": payload.get("externalConversationId"),
                       "body": payload.get("body", ""),
                       "confirmed": True, "targetConfirmed": True,
                       "attachments": payload.get("attachments", [])}
            if driver == "qq":
                request["cursor"] = self.qq_send_cursor(connector, profile)
            result = self.adapter_call(request)
            if result.get("ok") is True and isinstance(result.get("receipt"), str) and result.get("receipt"):
                if driver == "qq":
                    external_id = result.get("externalId")
                    if verified_qq_external_id(profile, external_id, result["receipt"]):
                        outcome = {"ok": True, "result": {
                            "receipt": result["receipt"], "externalId": external_id}}
                        receipt = json.loads(result["receipt"])
                        alias = qq_command_conversation_alias(
                            profile, payload.get("externalConversationId"))
                        if alias is not None:
                            priority_read = (alias, receipt["sourceId"])
                    else:
                        outcome = {"uncertain": True, "error": "qq_receipt_identity_unverified"}
                else:
                    outcome = {"ok": True, "result": {"receipt": result["receipt"]}}
                retryable = 0
            elif result.get("retryable") is True:
                if result.get("dispatched") is not False:
                    raise RuntimeError("send_result_ambiguous")
                outcome = {"retry": True, "error": str(result.get("error", "send_failed"))[:100]}
                retryable = 1
                self.db.execute("UPDATE command_ledger SET state='retry' WHERE connector_id=? AND idempotency_key=?",
                                (self.connector, key))
            elif result.get("ok") is False and result.get("dispatched") is False:
                outcome = {"ok": False, "error": str(result.get("error", "send_failed"))[:100]}
                retryable = 0
            else:
                outcome = {"uncertain": True, "error": "device_send_outcome_uncertain"}
                retryable = 0
        except SendPreDispatchError as error:
            outcome, retryable = {"ok": False, "dispatched": False, "error": str(error)}, 0
        except Exception:
            outcome, retryable = {"uncertain": True, "error": "device_send_outcome_uncertain"}, 0
        if not retryable:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("UPDATE command_ledger SET state='done',result=?,retryable=? WHERE connector_id=? AND idempotency_key=?",
                            (compact(outcome), retryable, self.connector, key))
            if priority_read is not None:
                self._register_qq_confirmed_read(profile, *priority_read)
        self.db.commit()
        self.complete(command, outcome)

    def register_connectors(self):
        for connector in self.connectors:
            if connector["id"] in self.registered or not self.eligible(connector["id"]):
                continue
            self.select_connector(connector)
            try:
                capabilities = ["receive_text", "receive_images"]
                if connector.get("receiveOnly") is not True:
                    capabilities.append("send_text")
                self.http_call("POST", "/api/connectors/register", {
                    "id": connector["id"], "kind": connector["kind"],
                    "accountLabel": connector["accountLabel"], "displayName": connector["displayName"],
                    "mode": "device_relay", "capabilities": capabilities,
                })
                self.registered.add(connector["id"])
                self.succeeded(connector["id"])
            except Exception:
                self.failed(connector["id"])

    def pass_once(self):
        self.ensure_active()
        delivered_connectors = set()
        for _ in range(MAX_DELIVERIES_PER_PASS):
            try:
                connector_id = self.flush_one()
                if not connector_id:
                    break
                delivered_connectors.add(connector_id)
                self.send_heartbeat(connector_id, "online")
            except Exception:
                break
        pending_connectors = {row[0] for row in self.db.execute("SELECT DISTINCT connector_id FROM outbox")}
        for connector in self.connectors:
            self.select_connector(connector)
            profile = connector["profile"]
            connector_id = connector["id"]
            ready = self.ensure_active()
            force_scan = self.auto_wake and ready and connector_id in self.wake_scan_pending
            scan_due = (time.monotonic() - self.last_scan[connector_id] >= self.scan_interval[connector_id])
            scan_allowed = (ready if self.auto_wake else self.eligible(connector_id))
            scan_retry_allowed = (force_scan or time.monotonic() >= self.wake_scan_retry_at[connector_id])
            if (connector_id not in pending_connectors and scan_allowed and scan_retry_allowed and
                    time.time() >= self.source_settle_until[connector_id] and
                    (force_scan or scan_due)):
                backpressured = False
                try:
                    scan_health = self.scan_profile(profile)
                    if scan_health is None:
                        backpressured = True
                    else:
                        self.health[connector_id] = scan_health
                        self.last_scan[connector_id] = time.monotonic()
                        if self.auto_wake:
                            self.wake_scan_succeeded(connector_id)
                        else:
                            self.succeeded(connector_id)
                except SourceReadError as error:
                    self.health[connector_id] = False
                    self.last_scan[connector_id] = time.monotonic() - self.scan_interval[connector_id]
                    failure_pid = (error.attach_failure_pid
                                   if type(error.attach_failure_pid) is int and error.attach_failure_pid > 1
                                   else None)
                    query_gate_pid = (error.query_gate_pending_pid
                                      if type(error.query_gate_pending_pid) is int
                                      and error.query_gate_pending_pid > 1 else None)
                    source_state_saved = self.source_read_failed(
                        connector_id, attach_failure_pid=failure_pid,
                        query_gate_pending_pid=query_gate_pid,
                    )
                    driver = self.connector_by_id[connector_id].get("kind")
                    if driver in {"qq", "wechat"}:
                        try:
                            observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
                                "+00:00", "Z")
                            sys.stderr.write(compact({
                                "observedAt": observed_at,
                                "driver": driver,
                                "consecutiveFailures": self.source_failures[connector_id],
                                "classification": ("explicit_attach" if failure_pid is not None else
                                                   "explicit_query_gate" if query_gate_pid is not None else
                                                   "source_unclassified"),
                                "processId": (failure_pid if failure_pid is not None else query_gate_pid),
                            }) + "\n")
                            sys.stderr.flush()
                        except Exception:
                            pass
                    if self.auto_wake:
                        self.wake_scan_failed(connector_id)
                        if source_state_saved:
                            if error.attach_failure_pid is not None:
                                self.recover_attach_after_failures(connector_id)
                            elif query_gate_pid is not None:
                                self.recover_query_gate_after_failures(connector_id)
                            else:
                                self.recover_source_after_failures(connector_id)
                    else:
                        self.failed(connector_id)
                except Exception:
                    self.health[connector_id] = False
                    self.attach_failure_streak[connector_id] = (None, 0)
                    self.query_gate_failure_streak[connector_id] = (None, 0)
                    self.last_scan[connector_id] = time.monotonic() - self.scan_interval[connector_id]
                    if self.auto_wake:
                        self.wake_scan_failed(connector_id)
                    else:
                        self.failed(connector_id)
                finally:
                    if force_scan and not backpressured:
                        self.wake_scan_pending.discard(connector_id)
                    self.cleanup_unreferenced_media()
            ready = self.ensure_active()
            source_fresh = (ready and self.health[connector_id] and
                            time.monotonic() - self.last_scan[connector_id] <=
                            self.scan_interval[connector_id] + 30)
            heartbeat_state = "online" if connector_id in delivered_connectors or source_fresh else "offline"
            self.send_heartbeat(connector_id, heartbeat_state)
        for connector in self.connectors:
            self.select_connector(connector)
            connector_id = self.connector
            ready = self.ensure_active()
            if (not ready or connector.get("receiveOnly") is True or not self.eligible(connector_id) or
                    not self.health.get(connector_id) or
                    time.time() < self.source_settle_until[connector_id] or
                    time.monotonic() - self.last_scan[connector_id] > self.scan_interval[connector_id] + 30):
                continue
            path = "/api/connectors/commands?connectorId=" + urllib.parse.quote(self.connector, safe="") + "&limit=1"
            try:
                commands = self.http_call("GET", path, None).get("commands", [])
                if commands:
                    if self.process_command(commands[0], connector["profile"]) is False:
                        self.failed(connector_id)
                        continue
                self.succeeded(connector_id)
            except Exception:
                self.failed(connector_id)


def main(argv):
    if len(argv) != 2:
        raise SystemExit("usage: device_runtime.py CONFIG.json")
    config_path = os.path.abspath(argv[1])
    if os.name == "posix" and os.stat(config_path).st_mode & 0o077:
        raise SystemExit("config_permissions_must_be_private")
    os.umask(0o077)
    with open(config_path, "r", encoding="utf-8") as source:
        config = json.load(source)
    config = resolve_local_paths(config, config_path)
    lock = None
    if os.name == "posix":
        database_parent = os.path.dirname(os.path.abspath(config["database"]))
        if not os.path.isdir(database_parent):
            os.makedirs(database_parent, mode=0o700)
        lock = open(config["database"] + ".lock", "a+")
        os.chmod(config["database"] + ".lock", 0o600)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit("device_runtime_already_running")
    relay = Relay(config)
    backoff = 1
    while True:
        try:
            relay.register_connectors()
            relay.pass_once()
            backoff = 1
            time.sleep(15)
        except KeyboardInterrupt:
            return
        except Exception:
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)


if __name__ == "__main__":
    main(sys.argv)
