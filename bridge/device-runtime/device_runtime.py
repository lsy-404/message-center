#!/usr/bin/env python3
"""Small direct HTTPS relay for a device-resident private adapter."""

import json
import hashlib
import os
import re
import selectors
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if os.name == "posix":
    import fcntl

MAX_RESPONSE = 1024 * 1024
MAX_EVENT = 256 * 1024
DEFAULT_OUTBOX_BYTES = 16 * 1024 * 1024
MAX_DELIVERIES_PER_PASS = 5


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise urllib.error.HTTPError(request.full_url, code, "redirect_refused", headers, response)


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
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def run_adapter(path, request, timeout=30):
    process = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, bufsize=0)
    process.stdin.write(compact(request).encode("utf-8"))
    process.stdin.close()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    output = bytearray()
    deadline = time.time() + timeout
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise RuntimeError("adapter_timeout")
            events = selector.select(min(remaining, 1))
            if not events:
                if process.poll() is not None:
                    break
                continue
            chunk = os.read(process.stdout.fileno(), 16 * 1024)
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > MAX_RESPONSE:
                raise RuntimeError("adapter_response_too_large")
    except Exception:
        process.kill()
        process.wait()
        raise
    finally:
        selector.close()
        process.stdout.close()
    if process.wait() != 0:
        raise RuntimeError("adapter_failed")
    value = json.loads(bytes(output).decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("adapter_invalid_response")
    return value


class Relay:
    def __init__(self, config, db=None, adapter_call=None, http_call=None):
        self.config = config
        self.db = db or open_database(config["database"])
        self.adapter_call = adapter_call or (lambda req: run_adapter(config["adapter"], req))
        self.http_call = http_call or self.request
        self.base = config["serviceUrl"].rstrip("/")
        if not self.base.startswith("https://"):
            raise ValueError("https_required")
        self.connectors = config["connectors"]
        if not self.connectors or len({item["id"] for item in self.connectors}) != len(self.connectors):
            raise ValueError("invalid_connector_configuration")
        if len({item["token"] for item in self.connectors}) != len(self.connectors):
            raise ValueError("connector_tokens_must_be_unique")
        for connector in self.connectors:
            if (not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{7,199}", connector["id"]) or
                    len(connector["token"]) < 32):
                raise ValueError("invalid_connector_configuration")
        self.connector_by_id = {item["id"]: item for item in self.connectors}
        self.connector = self.connectors[0]["id"]
        self.health = {item["id"]: False for item in self.connectors}
        self.last_scan = {item["id"]: 0 for item in self.connectors}
        self.scan_interval = {item["id"]: 300 for item in self.connectors}
        self.registered = set()

    def select_connector(self, connector):
        self.connector = connector["id"]
        self.active_connector = connector

    def headers(self):
        return {"Authorization": "Bearer " + self.active_connector["token"],
                "x-connector-id": self.connector}

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

    def count_bytes(self):
        row = self.db.execute("SELECT COALESCE(SUM(size),0) FROM outbox").fetchone()
        return int(row[0])

    def scan_profile(self, profile, history=False):
        if self.count_bytes() >= int(self.config.get("outboxMaxBytes", DEFAULT_OUTBOX_BYTES)):
            return None
        row = self.db.execute("SELECT value FROM cursors WHERE connector_id=? AND profile=?",
                              (self.connector, profile)).fetchone()
        cursor = json.loads(row[0]) if row else None
        limit = max(1, min(int(self.config.get("pageLimit", 20)), 20))
        result = self.adapter_call({"op": "scan", "profile": profile, "cursor": cursor,
                                    "limit": limit, "history": bool(history)})
        if result.get("ok") is not True or "cursor" not in result or not isinstance(result.get("messages"), list):
            raise RuntimeError("scan_failed")
        messages = result["messages"]
        if len(messages) > limit:
            raise RuntimeError("scan_page_too_large")
        encoded = []
        for message in messages:
            if (not isinstance(message, dict) or not isinstance(message.get("externalId"), str) or
                    not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{0,199}", message["externalId"])):
                raise RuntimeError("invalid_event")
            if message.get("attachments"):
                raise RuntimeError("adapter_file_receive_not_supported")
            if message.get("attachments"):
                raise RuntimeError("adapter_file_receive_not_supported")
            raw = compact({"connectorId": self.connector, "messages": [message]}).encode("utf-8")
            if len(raw) > MAX_EVENT:
                raise RuntimeError("event_too_large")
            encoded.append((self.connector, profile, str(message["externalId"]), compact(message), len(raw)))
        candidate = compact(result.get("cursor"))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            current = self.count_bytes()
            added = sum(item[4] for item in encoded)
            ceiling = int(self.config.get("outboxMaxBytes", DEFAULT_OUTBOX_BYTES))
            if current + added > ceiling:
                self.db.rollback()
                return None
            for item in encoded:
                self.db.execute("INSERT OR IGNORE INTO outbox(connector_id,profile,external_id,body,size) VALUES(?,?,?,?,?)", item)
            self.db.execute("INSERT INTO cursors(connector_id,profile,value) VALUES(?,?,?) "
                            "ON CONFLICT(connector_id,profile) DO UPDATE SET value=excluded.value",
                            (self.connector, profile, candidate))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        active = result.get("active") is True
        self.scan_interval[self.connector] = 60 if active else 300
        return result.get("health") == "online"

    def flush_one(self):
        row = self.db.execute("SELECT seq,connector_id,profile,external_id,body FROM outbox ORDER BY seq LIMIT 1").fetchone()
        if row is None:
            return False
        seq, connector_id, profile, external_id, body = row
        self.select_connector(self.connector_by_id[connector_id])
        self.http_call("POST", "/api/connectors/events",
                       {"connectorId": self.connector, "messages": [json.loads(body)]})
        self.db.execute("DELETE FROM outbox WHERE seq=?", (seq,))
        self.db.commit()
        return True

    def complete(self, command, result):
        self.http_call("POST", "/api/connectors/commands/" + urllib.parse.quote(command["id"], safe="") + "/complete",
                       {"connectorId": self.connector, "leaseToken": command["leaseToken"], **result})

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
                return
            self.db.execute("UPDATE command_ledger SET state='started',result=NULL WHERE connector_id=? AND idempotency_key=?",
                            (self.connector, key))
            self.db.commit()
        else:
            try:
                self.http_call("POST", "/api/connectors/commands/" +
                               urllib.parse.quote(command["id"], safe="") + "/lease",
                               {"connectorId": self.connector, "leaseToken": command["leaseToken"]})
            except Exception:
                return
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
        try:
            result = self.adapter_call({"op": "send", "profile": profile, "commandId": command["id"],
                                        "idempotencyKey": key,
                                        "conversationExternalId": payload.get("externalConversationId"),
                                        "body": payload.get("body", ""),
                                        "attachments": payload.get("attachments", [])})
            if result.get("ok") is True and isinstance(result.get("receipt"), str) and result.get("receipt"):
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
        except Exception:
            outcome, retryable = {"uncertain": True, "error": "device_send_outcome_uncertain"}, 0
        if not retryable:
            self.db.execute("UPDATE command_ledger SET state='done',result=?,retryable=? WHERE connector_id=? AND idempotency_key=?",
                            (compact(outcome), retryable, self.connector, key))
        self.db.commit()
        self.complete(command, outcome)

    def register_connectors(self):
        for connector in self.connectors:
            if connector["id"] in self.registered:
                continue
            self.select_connector(connector)
            self.http_call("POST", "/api/connectors/register", {
                "id": connector["id"], "kind": connector["kind"],
                "accountLabel": connector["accountLabel"], "displayName": connector["displayName"],
                "mode": "device_relay", "capabilities": ["receive_text", "send_text"],
            })
            self.registered.add(connector["id"])

    def pass_once(self):
        pending = self.db.execute("SELECT 1 FROM outbox LIMIT 1").fetchone() is not None
        for _ in range(MAX_DELIVERIES_PER_PASS):
            try:
                if not self.flush_one():
                    pending = False
                    break
                pending = self.db.execute("SELECT 1 FROM outbox LIMIT 1").fetchone() is not None
            except Exception:
                pending = True
                break
        for connector in self.connectors:
            self.select_connector(connector)
            profile = connector["profile"]
            if not pending and time.time() - self.last_scan[connector["id"]] >= self.scan_interval[connector["id"]]:
                try:
                    self.health[connector["id"]] = self.scan_profile(profile)
                    self.last_scan[connector["id"]] = time.time()
                except Exception:
                    self.health[connector["id"]] = False
                    self.last_scan[connector["id"]] = time.time()
            try:
                self.http_call("POST", "/api/connectors/heartbeat", {
                    "connectorId": self.connector,
                    "state": "online" if self.health[connector["id"]] and
                    time.time() - self.last_scan[connector["id"]] <= self.scan_interval[connector["id"]] + 30
                    else "offline"})
            except Exception:
                pass
        for connector in self.connectors:
            self.select_connector(connector)
            if (not self.health.get(self.connector) or
                    time.time() - self.last_scan[self.connector] > self.scan_interval[self.connector] + 30):
                continue
            path = "/api/connectors/commands?connectorId=" + urllib.parse.quote(self.connector, safe="") + "&limit=1"
            commands = self.http_call("GET", path, None).get("commands", [])
            if commands:
                self.process_command(commands[0], connector["profile"])


def main(argv):
    if len(argv) != 2:
        raise SystemExit("usage: device_runtime.py CONFIG.json")
    if os.name == "posix" and os.stat(argv[1]).st_mode & 0o077:
        raise SystemExit("config_permissions_must_be_private")
    with open(argv[1], "r", encoding="utf-8") as source:
        config = json.load(source)
    relay = Relay(config)
    lock = None
    if os.name == "posix":
        lock = open(config["database"] + ".lock", "a+")
        os.chmod(config["database"] + ".lock", 0o600)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit("device_runtime_already_running")
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
