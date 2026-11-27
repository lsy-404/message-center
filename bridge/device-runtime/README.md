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
     "nativeDesktop":"DESKTOP_MAIN"},
    {"id":"instance-selkies-qq","token":"injected-token-b",
     "kind":"qq","accountLabel":"Account A","displayName":"QQ A","profile":"main",
     "nativeDesktop":"DESKTOP_MAIN"}
  ],
  "outboxMaxBytes": 134217728,
  "pageLimit": 20
}
```

Use a real HTTPS origin and keep each bearer token private; the sample values are placeholders. The relay rejects redirects so credentials cannot be forwarded to another host. One process owns all configured connector identities and serializes polling and adapter calls across them. Run with `python3 device_runtime.py /path/to/private-config.json`. The supported drivers are `qq` and `wechat`.

`receiveOnly` is optional. When `true` the connector registers only `receive_text` and `receive_images` and the runtime does not poll for commands; otherwise it also registers `send_text`, `send_files` and `send_images` and runs approved sends through the adapter. For a send with files, the runtime first downloads each file from the Worker (`GET /api/files/<id>` with the connector token) into `<mediaDirectory>/outgoing`, checks its size and SHA-256, passes the local path to the adapter, and removes the copy afterwards. A failed download is retried without anything having been sent.

`nativeDesktop` is optional: the name of the Worker's VPC service binding that reaches this connector's `wechat-selkies` desktop (`^[A-Z][A-Z0-9_]{0,63}$`). The runtime validates it when it loads the configuration and sends it in `POST /api/connectors/register`. The Worker serves the desktop at `/native/<connector id>/` behind the administrator sign-in, reaching the container privately through Cloudflare Tunnel and Workers VPC, so the desktop needs no public hostname. See the Worker README for the binding and the `NATIVE_DESKTOPS` secret.

## Device adapter

`selkies_adapter.py` implements the process contract below and reads its own configuration, `selkies_adapter.json`, from the directory it lives in. The file must have mode `0600` and map each profile name to one container:

```json
{
  "profiles": {
    "main": {
      "desktopUrl": "http://127.0.0.1:13000",
      "tokenFile": "~/.local/share/wechat-selkies/master-token",
      "readFolders": false,
      "outgoingDirectory": "~/.local/share/wechat-selkies/config/message-center-outgoing",
      "containerOutgoingDirectory": "/config/message-center-outgoing"
    }
  }
}
```

`outgoingDirectory` is a folder inside the container's mounted config volume and `containerOutgoingDirectory` is the same folder as the container sees it; files to send are copied there under their own names (recipients see them) and removed after a day. Without both, sends with files are refused before anything is sent. `tokenFile` holds the container's Selkies master token (`SELKIES_MASTER_TOKEN`), which the adapter sends as `Authorization: Bearer`; it stays outside the repository. The runtime starts the adapter directly, so keep it executable (`chmod 755 selkies_adapter.py`). Use one container per account. A `wechat` connector and a `qq` connector can name the same profile when one container runs both clients. The adapter keeps the names of the chats it has seen, its recent sends and nothing else in `selkies_adapter.state.json` beside itself (mode `0600`).

### Container requirements

The adapter reads the desktop through the container's accessibility API. WeChat exposes it by default. QQ exposes its chat list only when started with `--force-renderer-accessibility`. `/usr/bin/qq` in the stock image is a symlink to `/opt/QQ/qq`, so bind-mounting a wrapper over it would overwrite the real binary.

The container runs in Selkies secure mode: a master token protects every API and stream for the adapter, and a controller session token, which the Worker adds to every request it forwards, serves the web UI's native view. The stock start script forces basic auth on, so the derived image also lets `SELKIES_ENABLE_BASIC_AUTH` turn it off (the build fails if that line of the upstream script changes):

```dockerfile
FROM ghcr.io/nickrunning/wechat-selkies:latest
RUN rm /usr/bin/qq && printf '#!/bin/sh\nexec /opt/QQ/qq --force-renderer-accessibility "$@"\n' > /usr/bin/qq && chmod 755 /usr/bin/qq
RUN grep -qx 'export SELKIES_ENABLE_BASIC_AUTH=true' /wechat-container-start \
 && sed -i 's/^export SELKIES_ENABLE_BASIC_AUTH=true$/export SELKIES_ENABLE_BASIC_AUTH=${SELKIES_ENABLE_BASIC_AUTH:-true}/' /wechat-container-start
```

Generate two random tokens (for example `openssl rand -hex 32`), keep them in mode-`0600` files, and write the session token into a tokens file inside the container's config volume, also mode `0600`: `{"<session-token>": {"role": "controller", "mk_control": true}}`. The same session token goes into the Worker's `NATIVE_DESKTOPS` secret. Then run the container with:

- `SELKIES_ENABLE_BASIC_AUTH=false`, `SELKIES_MASTER_TOKEN=<master-token>`, `SELKIES_TOKENS_FILE=/config/selkies-tokens.json`
- `SELKIES_FRAME_ANCESTORS=<Message Center origin>` so only Message Center can frame the desktop
- the published port bound to `127.0.0.1` only; the Worker reaches it through a Cloudflare Tunnel (`cloudflared` on the same machine, QUIC transport) and a Workers VPC HTTP service pointing at `127.0.0.1:<port>`
- `AUTO_START_WECHAT=true`, `AUTO_START_QQ=true`, and a non-empty `PASSWORD` (the start script still requires one)

Sign each client in once in Message Center's native view. Tick QQ's 自动登录 so it signs in again after a restart; WeChat asks for a confirmation on the phone after each container restart.

### What is read

- Each scan reads the chat-list last-message previews. It never opens a chat, so nothing is marked read.
- A chat is reported when it is new, its preview changed, or its unread count grew; the first scan therefore reports each chat's current preview once.
- A group chat is recognised by the `sender: ` or `sender：` prefix of its preview and remembered afterwards. A preview with the `[有人@我]` marker is a `mention` trigger; other group messages are `background`.
- Aggregate rows such as 公众号, 折叠的聊天, and 群助手 are not conversations and are not reported themselves.
- Each chat's 免打扰 (muted) and pinned state is synchronized with its conversation profile. WeChat names pinned rows 已置顶. QQ does not expose pinning in its accessibility tree, so the adapter scrolls the QQ list to the top, moves the pointer onto the title bar (a hovered row is drawn highlighted) and samples each row's background in a screenshot: a row whose colour differs from the most common row colour is pinned. The open chat is highlighted either way; it counts as pinned when it sits above an unpinned chat with a newer message, and otherwise keeps its last known state.
- When the 群助手 / 折叠的聊天 row itself is pinned it cannot move, so the adapter opens it as described below even without `readFolders`; chats pinned inside 群助手 are recognised the same way.
- With `readFolders: true` the adapter also opens 群助手 (QQ) or 折叠的聊天 (WeChat) when that row changes, or every 10 minutes, reads the chats on screen inside it with placement `folded`, and returns to the main list. Opening the folder means clicking its row in a list that reorders whenever a message arrives; the adapter clicks only after two reads 400 ms apart agree on the row and every row above it, but a message landing in between can still turn the click into opening the chat that moved into place, which marks it read. Pinning 群助手 in QQ keeps the row in place. The option is off by default.
- Only rows on screen are visible to the accessibility tree, so the adapter restores and maximizes the client window before reading. A client hidden to the panel tray is shown again from its tray button; the adapter never presses Escape, which hides both clients to the tray.
- Failures such as `client_not_running`, `client_signed_out`, `desktop_unreachable`, and `desktop_auth_refused` return `{"ok":false,"sourceReadStatus":"failed","error":code}`; the runtime marks the source failed and backs off.

## Adapter process contract

The relay invokes the configured executable directly, without a shell. Each invocation gets one UTF-8 JSON request on stdin and must write exactly one UTF-8 JSON object to stdout. Diagnostics belong on stderr. Requests are bounded by a timeout.

Every `scan` response must include `sourceReadStatus` as `complete` or `failed`; the former `sourceReadOk` field and any other value are rejected. `complete` must use `ok: true` and may still report `health: degraded`. `failed` must use `ok: false` and follows the source failure path without committing scan progress. Only validated messages and the candidate cursor are committed.

Scan requests also include a connector-specific `mediaDirectory` and `maxMediaBytes`, the remaining connector outbox byte budget for staged images. An adapter may return at most 20 image attachments per message with `{externalId,fileName,mimeType,sizeBytes,sha256,stagingKey}` after atomically writing each completed file under that directory. A staging key is a single filename matching `^[A-Za-z0-9][A-Za-z0-9._-]{0,179}$`; it cannot contain a path. The runtime checks the file type, size, and SHA-256 with 64 KiB reads, then streams uploads in 64 KiB chunks. It counts image bytes in the durable outbox ceiling and commits source cursor and event metadata together. `stagingKey` stays local and is removed from cloud metadata. A lost upload or ingest response is retried with the same external attachment ID. Repeated events with the same external ID and body may add uploaded attachments; conflicting metadata or content is rejected. Routine inbound `group` + `background` messages (`isSelf` absent or false), including image messages, use the Worker's isolated group-text-backups endpoint and remain outside `agent_queue`; image-only events use body `[图片]`. Self-authored background group messages use normal event ingestion. `history` remains false in routine scans.

A scan may also return `conversationProfiles`, with at most 20 entries. Each entry contains `conversationExternalId` and `displayName`, plus optional type, placement, pin, unread count, preview and ISO timestamp fields. The runtime synchronizes these through the existing conversation profile API before committing the scan cursor. A failed update leaves the cursor unchanged.

`send` request: `{"op":"send","profile":"profile-a","commandId":"...","idempotencyKey":"...","conversationExternalId":"...","body":"...","attachments":[]}`. Response success is `{"ok":true,"receipt":"..."}` with a nonempty receipt. A retryable failure must explicitly mean the operation was not dispatched: `{"ok":false,"retryable":true,"dispatched":false,"error":"short_code"}`. A definite pre-dispatch refusal is `{"ok":false,"dispatched":false,"error":"short_code"}`. Ambiguous or dispatched-without-receipt outcomes are uncertain. A process restart after the operation begins is treated as uncertain and is never automatically sent again. `selkies_adapter.py` sends text and up to 20 files to a chat a scan has seen; attachments are `{fileName, mimeType, localPath}` entries:

- It opens the chat: WeChat by scrolling the chat list (or 折叠的聊天) to the row and clicking it once two reads agree, QQ through the search box, whose results do not reorder.
- It checks that the input box belongs to that chat and holds no draft.
- Each file goes in first, one at a time, through the client's own file picker: WeChat's 发送文件 (images arrive as 图片, GIFs as 动画表情), QQ's 图片 button for images (or 文件 where the chat has none, such as 我的手机) and 文件 for other files, whose confirmation must name the chat and the file before the adapter presses 发送(n). After sending, it waits up to 90 seconds for the file to appear as the last message (QQ files: until they show 已发送).
- Then it types the text (new lines with Shift+Enter; 「 and 」 are pressed as keysyms because typing them produces 〈〉) and reads the input back; any mismatch clears the input and refuses with `dispatched: false`, or, once a file already went out, reports an uncertain result.
- It sends (WeChat with Enter, QQ with the 发送 button), then waits until the input is empty and the last message in the chat equals the text. Only then does it answer with a receipt. A result it cannot confirm carries no `dispatched: false`, so the runtime records it as uncertain for manual review and never sends it again.
- The next scans recognise the chat-list preview of a message the adapter just sent and do not report it as an incoming message; the outbound message already exists in Message Center.

## Runtime limits

The single process scans configured profiles sequentially, one page of at most 20 messages each, every 15 seconds while a page reports `more`, 60 seconds while `active`, and 300 seconds otherwise. A failed scan marks the source offline and backs off with bounded exponential delay up to 300 seconds. Normal event responses with `suppressed > 0` do not acknowledge or remove the outbox record. The outbox has a byte ceiling; pending records are drained before new scans, and a full queue stops collection so the source cursor cannot move past unspooled messages. Delivery rotates fairly across connectors and removes a record only after a successful Worker response. A failed connector is skipped while other connectors continue draining.

An optional macOS launchd sample is provided in `launchd.plist.example`; replace every placeholder path before enabling it. It keeps `/usr/bin/python3 device_runtime.py <config>` running. This package does not install or activate a background service automatically.
