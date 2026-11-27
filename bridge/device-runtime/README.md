# Device runtime

This Python 3.9 standard-library relay connects a device adapter directly to the Message Center Worker over HTTPS. It runs on any macOS or Linux machine that hosts, or can reach over HTTP, a `wechat-selkies` container; no desktop session, USB connection, or jailbroken device is involved. The device adapter shipped here, `selkies_adapter.py`, reads the official WeChat and QQ Linux desktop clients running in that container.

## Configuration

Store a UTF-8 JSON configuration at a private local path with mode `0600`. Relative adapter, database, and media paths resolve from the configuration file directory. If omitted, `mediaDirectory` defaults to `<database>.media`; the runtime creates it with mode `0700`.

```json
{
  "serviceUrl": "https://messages.example.invalid",
  "database": "./message-center.sqlite3",
  "adapter": "./selkies_adapter.py",
  "mediaDirectory": "./message-center-media",
  "connectors": [
    {"id":"instance-selkies-wechat","token":"injected-token-a",
     "kind":"wechat","accountLabel":"Account A","displayName":"WeChat A","profile":"main",
     "receiveOnly":true,"nativeUrl":"http://localhost:13000/?token=browser-token"},
    {"id":"instance-selkies-qq","token":"injected-token-b",
     "kind":"qq","accountLabel":"Account A","displayName":"QQ A","profile":"main",
     "receiveOnly":true,"nativeUrl":"http://localhost:13000/?token=browser-token"}
  ],
  "outboxMaxBytes": 134217728,
  "pageLimit": 20
}
```

Use a real HTTPS origin and keep each bearer token private; the sample values are placeholders. The relay rejects redirects so credentials cannot be forwarded to another host. One process owns all configured connector identities and serializes polling and adapter calls across them. Run with `python3 device_runtime.py /path/to/private-config.json`. The supported drivers are `qq` and `wechat`.

`receiveOnly` must be `true` for every connector served by `selkies_adapter.py`: the adapter reads chat lists and never sends. With `receiveOnly` the connector registers only `receive_text` and `receive_images` and the runtime does not poll for commands. Connectors that are not `receiveOnly` keep the command and send-ledger path for other adapters.

`nativeUrl` is optional: the browser-facing `http://` or `https://` address (at most 500 characters) of the connector's `wechat-selkies` desktop. The runtime validates it when it loads the configuration and sends it as `nativeUrl` in `POST /api/connectors/register`, so the web UI can embed the desktop in its native mode. `nativeUrl` is the address a browser reaches, which can differ from the `desktopUrl` the adapter uses, and carries the container's browser token as `?token=` (see below). The Worker returns it only to signed-in administrators.

## Device adapter

`selkies_adapter.py` implements the process contract below and reads its own configuration, `selkies_adapter.json`, from the directory it lives in. The file must have mode `0600` and map each profile name to one container:

```json
{
  "profiles": {
    "main": {
      "desktopUrl": "http://127.0.0.1:13000",
      "tokenFile": "~/.local/share/wechat-selkies/master-token"
    }
  }
}
```

`tokenFile` holds the container's Selkies master token (`SELKIES_MASTER_TOKEN`), which the adapter sends as `Authorization: Bearer`; it stays outside the repository. The runtime starts the adapter directly, so keep it executable (`chmod 755 selkies_adapter.py`). Use one container per account. A `wechat` connector and a `qq` connector can name the same profile when one container runs both clients.

### Container requirements

The adapter reads the desktop through the container's accessibility API. WeChat exposes it by default. QQ exposes its chat list only when started with `--force-renderer-accessibility`. `/usr/bin/qq` in the stock image is a symlink to `/opt/QQ/qq`, so bind-mounting a wrapper over it would overwrite the real binary.

The web UI's native mode embeds the desktop in an iframe, where browsers do not show an HTTP basic-auth prompt, so the container runs in Selkies secure mode instead: a master token protects every API and stream, and a controller token in the page address (`?token=`) signs the browser in. The stock start script forces basic auth on, so the derived image also lets `SELKIES_ENABLE_BASIC_AUTH` turn it off (the build fails if that line of the upstream script changes):

```dockerfile
FROM ghcr.io/nickrunning/wechat-selkies:latest
RUN rm /usr/bin/qq && printf '#!/bin/sh\nexec /opt/QQ/qq --force-renderer-accessibility "$@"\n' > /usr/bin/qq && chmod 755 /usr/bin/qq
RUN grep -qx 'export SELKIES_ENABLE_BASIC_AUTH=true' /wechat-container-start \
 && sed -i 's/^export SELKIES_ENABLE_BASIC_AUTH=true$/export SELKIES_ENABLE_BASIC_AUTH=${SELKIES_ENABLE_BASIC_AUTH:-true}/' /wechat-container-start
```

Generate two random tokens (for example `openssl rand -hex 32`), keep them in mode-`0600` files, and write the browser token into a tokens file inside the container's config volume, also mode `0600`: `{"<browser-token>": {"role": "controller", "mk_control": true}}`. Then run the container with:

- `SELKIES_ENABLE_BASIC_AUTH=false`, `SELKIES_MASTER_TOKEN=<master-token>`, `SELKIES_TOKENS_FILE=/config/selkies-tokens.json`
- `SELKIES_FRAME_ANCESTORS=<Message Center origin>` so only Message Center can frame the desktop
- `AUTO_START_WECHAT=true`, `AUTO_START_QQ=true`, and a non-empty `PASSWORD` (the start script still requires one)

Sign each client in once in the browser desktop (`<desktop>/?token=<browser-token>`). Tick QQ's 自动登录 so it signs in again after a restart; WeChat asks for a confirmation on the phone after each container restart.

### What is read

- Each scan reads the chat-list last-message previews. It never opens a chat, so nothing is marked read.
- A chat is reported when it is new, its preview changed, or its unread count grew; the first scan therefore reports each chat's current preview once.
- A group chat is recognised by the `sender: ` or `sender：` prefix of its preview and remembered afterwards. A preview with the `[有人@我]` marker is a `mention` trigger; other group messages are `background`.
- Aggregate rows such as 公众号, 折叠的聊天, and 群助手 are skipped.
- Only rows on screen are visible to the accessibility tree, so the adapter restores and maximizes the client window before reading.
- Failures such as `client_not_running`, `client_signed_out`, `desktop_unreachable`, and `desktop_auth_refused` return `{"ok":false,"sourceReadStatus":"failed","error":code}`; the runtime marks the source failed and backs off.

## Adapter process contract

The relay invokes the configured executable directly, without a shell. Each invocation gets one UTF-8 JSON request on stdin and must write exactly one UTF-8 JSON object to stdout. Diagnostics belong on stderr. Requests are bounded by a timeout.

Every `scan` response must include `sourceReadStatus` as `complete` or `failed`; the former `sourceReadOk` field and any other value are rejected. `complete` must use `ok: true` and may still report `health: degraded`. `failed` must use `ok: false` and follows the source failure path without committing scan progress. Only validated messages and the candidate cursor are committed.

Scan requests also include a connector-specific `mediaDirectory` and `maxMediaBytes`, the remaining connector outbox byte budget for staged images. An adapter may return at most 20 image attachments per message with `{externalId,fileName,mimeType,sizeBytes,sha256,stagingKey}` after atomically writing each completed file under that directory. A staging key is a single filename matching `^[A-Za-z0-9][A-Za-z0-9._-]{0,179}$`; it cannot contain a path. The runtime checks the file type, size, and SHA-256 with 64 KiB reads, then streams uploads in 64 KiB chunks. It counts image bytes in the durable outbox ceiling and commits source cursor and event metadata together. `stagingKey` stays local and is removed from cloud metadata. A lost upload or ingest response is retried with the same external attachment ID. Repeated events with the same external ID and body may add uploaded attachments; conflicting metadata or content is rejected. Routine inbound `group` + `background` messages (`isSelf` absent or false), including image messages, use the Worker's isolated group-text-backups endpoint and remain outside `agent_queue`; image-only events use body `[图片]`. Self-authored background group messages use normal event ingestion. `history` remains false in routine scans.

A scan may also return `conversationProfiles`, with at most 20 entries. Each entry contains `conversationExternalId` and `displayName`, plus optional type, placement, pin, unread count, preview and ISO timestamp fields. The runtime synchronizes these through the existing conversation profile API before committing the scan cursor. A failed update leaves the cursor unchanged.

`send` request: `{"op":"send","profile":"profile-a","commandId":"...","idempotencyKey":"...","conversationExternalId":"...","body":"...","attachments":[]}`. Response success is `{"ok":true,"receipt":"..."}` with a nonempty receipt. A retryable failure must explicitly mean the operation was not dispatched: `{"ok":false,"retryable":true,"dispatched":false,"error":"short_code"}`. A definite pre-dispatch refusal is `{"ok":false,"dispatched":false,"error":"short_code"}`. Ambiguous or dispatched-without-receipt outcomes are uncertain. A process restart after the operation begins is treated as uncertain and is never automatically sent again. `selkies_adapter.py` always answers `send` with `send_unsupported`, which is why its connectors must be `receiveOnly`.

## Runtime limits

The single process scans configured profiles sequentially, one page of at most 20 messages each, every 15 seconds while a page reports `more`, 60 seconds while `active`, and 300 seconds otherwise. A failed scan marks the source offline and backs off with bounded exponential delay up to 300 seconds. Normal event responses with `suppressed > 0` do not acknowledge or remove the outbox record. The outbox has a byte ceiling; pending records are drained before new scans, and a full queue stops collection so the source cursor cannot move past unspooled messages. Delivery rotates fairly across connectors and removes a record only after a successful Worker response. A failed connector is skipped while other connectors continue draining.

An optional macOS launchd sample is provided in `launchd.plist.example`; replace every placeholder path before enabling it. It keeps `/usr/bin/python3 device_runtime.py <config>` running. This package does not install or activate a background service automatically.
