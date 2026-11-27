"""A WebSocket per connector on which the Worker announces queued commands, so they are leased at once."""

import base64
import hashlib
import os
import select
import socket
import ssl
import struct
import threading
import time
import urllib.parse


# The edge closes a WebSocket idle for 100 seconds.
PING_INTERVAL = 60
DEAD_AFTER = 150
CONNECT_TIMEOUT = 20
MAX_FRAME = 64 * 1024
MAX_BACKOFF = 60
ACCEPT_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class SignalClosed(Exception):
    pass


class CommandSignal(threading.Thread):
    """Keeps one connector's signal socket open, reconnecting with backoff. `on_signal(connector_id)` runs on this
    thread when a command is announced and after each successful (re)connect, since commands may have been queued
    while the socket was down. `connected` is true while the socket is open."""

    def __init__(self, base, connector_id, token, on_signal):
        super().__init__(name="command-signal-" + connector_id, daemon=True)
        self.url = urllib.parse.urlsplit(base)
        self.connector_id = connector_id
        self.token = token
        self.on_signal = on_signal
        self.connected = False

    def run(self):
        backoff = 1
        while True:
            sock = None
            try:
                sock = self.connect()
                self.connected = True
                backoff = 1
                self.on_signal(self.connector_id)
                self.listen(sock)
            except (OSError, ssl.SSLError, SignalClosed, ValueError):
                pass
            finally:
                self.connected = False
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)

    def connect(self):
        host = self.url.hostname
        port = self.url.port or 443
        raw = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = (self.url.path.rstrip("/") or "") + "/api/connectors/signal"
        request = (
            "GET {} HTTP/1.1\r\nHost: {}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            "Sec-WebSocket-Key: {}\r\nSec-WebSocket-Version: 13\r\nAuthorization: Bearer {}\r\n"
            "x-connector-id: {}\r\nUser-Agent: MessageCenterDevice/1.0\r\n\r\n"
        ).format(path, host, key, self.token, self.connector_id)
        sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk or len(response) > 16384:
                raise SignalClosed("handshake_failed")
            response += chunk
        head, _, rest = response.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        if not lines[0].startswith("HTTP/1.1 101"):
            raise SignalClosed("handshake_refused")
        headers = {name.strip().lower(): value.strip() for name, _, value in (line.partition(":") for line in lines[1:])}
        expected = base64.b64encode(hashlib.sha1((key + ACCEPT_GUID).encode("ascii")).digest()).decode("ascii")
        if headers.get("sec-websocket-accept") != expected:
            raise SignalClosed("handshake_mismatch")
        if rest:
            raise SignalClosed("unexpected_data")
        return sock

    def listen(self, sock):
        last_seen = last_ping = time.monotonic()
        while True:
            now = time.monotonic()
            if now - last_seen > DEAD_AFTER:
                raise SignalClosed("silent")
            if now - last_ping >= PING_INTERVAL:
                self.send(sock, 0x1, b"ping")
                last_ping = now
            # TLS may already hold a decrypted frame that select cannot see.
            if not sock.pending() and not select.select([sock], [], [], 1)[0]:
                continue
            sock.settimeout(CONNECT_TIMEOUT)
            opcode, payload = self.read_frame(sock)
            last_seen = time.monotonic()
            if opcode == 0x1 and payload == b"command":
                self.on_signal(self.connector_id)
            elif opcode == 0x9:
                self.send(sock, 0xA, payload)
            elif opcode == 0x8:
                self.send(sock, 0x8, payload[:2])
                raise SignalClosed("closed")

    @staticmethod
    def read_exact(sock, count):
        data = b""
        while len(data) < count:
            chunk = sock.recv(count - len(data))
            if not chunk:
                raise SignalClosed("eof")
            data += chunk
        return data

    def read_frame(self, sock):
        first, second = self.read_exact(sock, 2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self.read_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self.read_exact(sock, 8))[0]
        if second & 0x80 or not first & 0x80 or length > MAX_FRAME:
            raise SignalClosed("unsupported_frame")
        return opcode, self.read_exact(sock, length)

    @staticmethod
    def send(sock, opcode, payload):
        # Client frames must be masked.
        mask = os.urandom(4)
        header = bytes([0x80 | opcode, 0x80 | len(payload)])
        sock.sendall(header + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload)))
