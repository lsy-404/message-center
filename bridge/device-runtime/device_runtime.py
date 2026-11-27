#!/usr/bin/env python3
"""Small direct HTTPS relay for a device adapter process."""

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
ADAPTER_FETCH_TIMEOUT = 180


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise urllib.error.HTTPError(request.full_url, code, "redirect_refused", headers, response)


class SourceReadError(RuntimeError):
    pass


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
    """)
    return db


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


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
        # Each file goes through the client's picker and upload before the next one.
        return ADAPTER_SEND_TIMEOUT + 120 * len(request.get("attachments") or [])
    if operation == "fetch":
        return ADAPTER_FETCH_TIMEOUT
    raise ValueError("unsupported_adapter_operation")


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
            native_desktop = connector.get("nativeDesktop")
            if native_desktop is not None and (
                    not isinstance(native_desktop, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", native_desktop)):
                raise ValueError("invalid_native_desktop")
        self.connector_by_id = {item["id"]: item for item in self.connectors}
        self.connector = self.connectors[0]["id"]
        self.health = {item["id"]: False for item in self.connectors}
        self.last_scan = {item["id"]: float("-inf") for item in self.connectors}
        self.scan_interval = {item["id"]: 300 for item in self.connectors}
        self.registered = set()
        self.flush_next_index = 0
        self.failures = {item["id"]: 0 for item in self.connectors}
        self.retry_at = {item["id"]: 0 for item in self.connectors}
        self.outbox_failures = {item["id"]: 0 for item in self.connectors}
        self.outbox_retry_at = {item["id"]: 0 for item in self.connectors}
        self.heartbeat_failures = {item["id"]: 0 for item in self.connectors}
        self.heartbeat_retry_at = {item["id"]: 0 for item in self.connectors}
        self.heartbeat_last_state = {item["id"]: None for item in self.connectors}
        self.heartbeat_last_sent = {item["id"]: float("-inf") for item in self.connectors}

    def close(self):
        self.db.close()

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

    def outbox_eligible(self, connector_id):
        return time.monotonic() >= self.outbox_retry_at[connector_id]

    def outbox_failed(self, connector_id):
        count = self.outbox_failures[connector_id] + 1
        self.outbox_failures[connector_id] = count
        self.outbox_retry_at[connector_id] = time.monotonic() + min(15 * (2 ** min(count - 1, 5)), 300)

    def outbox_succeeded(self, connector_id):
        self.outbox_failures[connector_id] = 0
        self.outbox_retry_at[connector_id] = 0

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

    def connector_heartbeat_state(self, connector_id):
        if time.monotonic() - self.last_scan[connector_id] > self.scan_interval[connector_id] + 30:
            return "offline"
        return "online" if self.health[connector_id] else "offline"

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
        scan_request = {"op": "scan", "driver": driver,
                                        "profile": profile, "cursor": cursor,
                                        "limit": limit, "maxBytes": MAX_SCAN_RESPONSE,
                                        "maxEventBytes": MAX_EVENT, "mediaDirectory": self.media_directory_for(self.connector),
                                        "maxMediaBytes": remaining, "history": bool(history)}
        try:
            result = self.adapter_call(scan_request)
        except Exception as error:
            raise SourceReadError("source_read_failed") from error
        if not isinstance(result, dict):
            raise RuntimeError("invalid_scan_result")
        source_read_status = result.get("sourceReadStatus")
        if ("sourceReadOk" in result
                or type(source_read_status) is not str
                or source_read_status not in {"complete", "failed"}):
            raise RuntimeError("invalid_scan_result")
        if source_read_status == "failed":
            if result.get("ok") is not False:
                raise RuntimeError("invalid_scan_result")
            code = result.get("error")
            raise SourceReadError(code if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]{1,40}", code) else "source_read_failed")
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
            if "presentation" in message:
                raise RuntimeError("invalid_event_presentation")
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
        self.scan_interval[self.connector] = 2 if result.get("more") is True else (5 if active else 300)
        return result.get("health") == "online"

    def validate_staged_attachment(self, attachment, any_type=False):
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
                not isinstance(mime_type, str) or not (IMAGE_MIME.fullmatch(mime_type) or (any_type and mime_type == "application/octet-stream")) or
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
            if not self.outbox_eligible(connector_id):
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
                self.outbox_failed(connector_id)
                continue
            self._delete_outbox_prefix(connector_id, rows)
            for attachment in attachments:
                try:
                    os.remove(os.path.join(self.media_directory_for(connector_id), attachment["stagingKey"]))
                except OSError:
                    pass
            self.outbox_succeeded(connector_id)
            self.flush_next_index = (index + 1) % count
            return connector_id
        return None

    def complete(self, command, result):
        self.http_call("POST", "/api/connectors/commands/" + urllib.parse.quote(command["id"], safe="") + "/complete",
                       {"connectorId": self.connector, "leaseToken": command["leaseToken"], **result})

    def fetch_media(self, command, profile):
        """Runs an owner-requested fetch of a chat's image or file and uploads it for the target message. Fetching
        sends nothing, so a failure is final and never ambiguous."""
        payload = command.get("payload") or {}
        try:
            self.http_call("POST", "/api/connectors/commands/" + urllib.parse.quote(command["id"], safe="") + "/lease",
                           {"connectorId": self.connector, "leaseToken": command["leaseToken"]})
        except Exception:
            return False
        outcome = {"ok": False, "error": "fetch_failed"}
        try:
            connector = self.connector_by_id[self.connector]
            result = self.adapter_call({
                "op": "fetch", "driver": connector.get("kind"), "profile": profile,
                "conversationExternalId": payload.get("externalConversationId"),
                "kind": payload.get("kind"), "fileName": payload.get("fileName"),
                "mediaDirectory": self.media_directory_for(self.connector),
                "maxMediaBytes": MAX_ATTACHMENT_BYTES})
            if result.get("ok") is True:
                attachment = self.validate_staged_attachment(result.get("attachment"), any_type=True)
                self.upload_attachment({"conversationExternalId": payload.get("externalConversationId")}, attachment)
                outcome = {"ok": True, "result": {"attachment": {key: value for key, value in attachment.items()
                                                                 if key != "stagingKey"}}}
                try:
                    os.unlink(os.path.join(self.media_directory_for(self.connector), attachment["stagingKey"]))
                except OSError:
                    pass
            else:
                outcome = {"ok": False, "error": str(result.get("error", "fetch_failed"))[:100]}
        except Exception as error:
            outcome = {"ok": False, "error": str(error)[:100] or "fetch_failed"}
        self.complete(command, outcome)

    def process_command(self, command, profile):
        if command.get("kind") == "fetch_media":
            return self.fetch_media(command, profile)
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
        downloaded = []
        try:
            connector = self.connector_by_id[self.connector]
            driver = connector.get("kind")
            if driver not in {"qq", "wechat"}:
                raise RuntimeError("unsupported_connector_driver")
            try:
                for attachment in payload.get("attachments") or []:
                    downloaded.append(self.download_attachment(attachment))
            except Exception:
                result = {"ok": False, "retryable": True, "dispatched": False, "error": "attachment_download_failed"}
            else:
                request = {"op": "send", "driver": driver,
                           "profile": profile, "commandId": command["id"],
                           "idempotencyKey": key,
                           "conversationExternalId": payload.get("externalConversationId"),
                           "body": payload.get("body", ""),
                           "confirmed": True, "targetConfirmed": True,
                           "attachments": downloaded}
                result = self.adapter_call(request)
            if result.get("ok") is True and isinstance(result.get("receipt"), str) and result.get("receipt"):
                outcome = {"ok": True, "result": {"receipt": result["receipt"]}}
                retryable = 0
            elif result.get("retryable") is True:
                if result.get("dispatched") is not False:
                    raise RuntimeError("send_result_ambiguous")
                outcome = {"retry": True, "error": str(result.get("error", "send_failed"))[:100]}
                retryable = 1
                self.db.execute("UPDATE command_ledger SET state='retry',result=?,retryable=1 "
                                "WHERE connector_id=? AND idempotency_key=?",
                                (compact(outcome), self.connector, key))
            elif result.get("ok") is False and result.get("dispatched") is False:
                outcome = {"ok": False, "error": str(result.get("error", "send_failed"))[:100]}
                retryable = 0
            else:
                outcome = {"uncertain": True, "error": "device_send_outcome_uncertain"}
                retryable = 0
        except Exception:
            outcome, retryable = {"uncertain": True, "error": "device_send_outcome_uncertain"}, 0
        finally:
            for attachment in downloaded:
                try:
                    os.unlink(attachment["localPath"])
                except OSError:
                    pass
        if not retryable:
            self.db.execute("UPDATE command_ledger SET state='done',result=?,retryable=? WHERE connector_id=? AND idempotency_key=?",
                            (compact(outcome), retryable, self.connector, key))
        self.db.commit()
        self.complete(command, outcome)

    def download_attachment(self, attachment):
        """Fetches one outbound file of the leased command into the outgoing media folder and checks its size and
        SHA-256; returns the adapter's attachment entry with `localPath`."""
        if not isinstance(attachment, dict):
            raise RuntimeError("invalid_attachment")
        file_id = str(attachment.get("id") or "")
        size = attachment.get("sizeBytes")
        sha256 = str(attachment.get("sha256") or "")
        if (not re.fullmatch(r"[a-zA-Z0-9._:-]{1,200}", file_id)
                or attachment.get("downloadPath") != "/api/files/" + file_id
                or isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_ATTACHMENT_BYTES
                or not re.fullmatch(r"[0-9a-f]{64}", sha256)):
            raise RuntimeError("invalid_attachment")
        folder = os.path.join(self.media_directory, "outgoing")
        os.makedirs(folder, mode=0o700, exist_ok=True)
        path = os.path.join(folder, sha256 + "-" + str(int(time.time() * 1000)))
        headers = dict(self.headers(), Accept="*/*")
        request = urllib.request.Request(self.base + attachment["downloadPath"], headers=headers, method="GET")
        digest = hashlib.sha256()
        written = 0
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response, \
                    open(path, "wb") as handle:
                if response.geturl() != request.full_url:
                    raise RuntimeError("redirect_refused")
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > size:
                        raise RuntimeError("attachment_size_mismatch")
                    digest.update(chunk)
                    handle.write(chunk)
            if written != size or digest.hexdigest() != sha256:
                raise RuntimeError("attachment_digest_mismatch")
        except BaseException:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        return {"fileName": str(attachment.get("fileName") or ""), "mimeType": str(attachment.get("mimeType") or ""),
                "sizeBytes": size, "sha256": sha256, "localPath": path}

    def register_connectors(self):
        for connector in self.connectors:
            if connector["id"] in self.registered or not self.eligible(connector["id"]):
                continue
            self.select_connector(connector)
            try:
                capabilities = ["receive_text", "receive_images"]
                if connector.get("receiveOnly") is not True:
                    # Files arrive only through owner-requested fetches, which are commands.
                    capabilities.extend(["send_text", "send_files", "send_images", "receive_files"])
                payload = {
                    "id": connector["id"], "kind": connector["kind"],
                    "accountLabel": connector["accountLabel"], "displayName": connector["displayName"],
                    "mode": "device_relay", "capabilities": capabilities,
                }
                if connector.get("nativeDesktop"):
                    payload["nativeDesktop"] = connector["nativeDesktop"]
                self.http_call("POST", "/api/connectors/register", payload)
                self.registered.add(connector["id"])
                self.succeeded(connector["id"])
            except Exception:
                self.failed(connector["id"])

    def pass_once(self):
        for _ in range(MAX_DELIVERIES_PER_PASS):
            try:
                connector_id = self.flush_one()
                if not connector_id:
                    break
                self.send_heartbeat(connector_id, self.connector_heartbeat_state(connector_id))
            except Exception:
                break
        for connector in self.connectors:
            self.select_connector(connector)
            profile = connector["profile"]
            connector_id = connector["id"]
            if (self.eligible(connector_id)
                    and time.monotonic() - self.last_scan[connector_id] >= self.scan_interval[connector_id]):
                try:
                    scan_health = self.scan_profile(profile)
                    if scan_health is not None:
                        self.health[connector_id] = scan_health
                        self.last_scan[connector_id] = time.monotonic()
                        self.succeeded(connector_id)
                except Exception as error:
                    self.health[connector_id] = False
                    self.last_scan[connector_id] = time.monotonic() - self.scan_interval[connector_id]
                    self.failed(connector_id)
                    self.log_scan_failure(connector_id, error)
                finally:
                    self.cleanup_unreferenced_media()
            self.send_heartbeat(connector_id, self.connector_heartbeat_state(connector_id))
        for connector in self.connectors:
            self.select_connector(connector)
            connector_id = self.connector
            if (connector.get("receiveOnly") is True or not self.eligible(connector_id)
                    or not self.health.get(connector_id)
                    or time.monotonic() - self.last_scan[connector_id] > self.scan_interval[connector_id] + 30):
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

    def log_scan_failure(self, connector_id, error):
        cause = error.__cause__ or error
        observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        try:
            sys.stderr.write(compact({"observedAt": observed_at, "connectorId": connector_id,
                                      "error": str(cause)[:100] or type(cause).__name__}) + "\n")
            sys.stderr.flush()
        except Exception:
            pass


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
    try:
        while True:
            try:
                relay.register_connectors()
                relay.pass_once()
                backoff = 1
                time.sleep(5)
            except KeyboardInterrupt:
                return
            except Exception:
                time.sleep(backoff)
                backoff = min(backoff * 2, 300)
    finally:
        relay.close()


if __name__ == "__main__":
    main(sys.argv)
