# Device runtime

This Python 3.9 standard-library relay connects a device directly to the Message Center Worker over HTTPS. It does not require a desktop service, USB connection, or LAN connection. Vendor-specific device access stays in a private executable implementing the JSON contract below.

## Configuration

Store a UTF-8 JSON configuration at a private local path with mode `0600`. Relative adapter, database, and media paths resolve from the configuration file directory. If omitted, `mediaDirectory` defaults to `<database>.media`; the runtime creates it with mode `0700`.

```json
{
  "serviceUrl": "https://messages.example.invalid",
  "database": "./message-center.sqlite3",
  "adapter": "./private-device-adapter",
  "mediaDirectory": "./message-center-media",
  "connectors": [
    {"id":"instance-device-primary","token":"injected-token-a",
     "kind":"im","accountLabel":"Account A","displayName":"Device relay A","profile":"profile-a",
     "receiveOnly":true},
    {"id":"instance-device-secondary","token":"injected-token-b",
     "kind":"im","accountLabel":"Account B","displayName":"Device relay B","profile":"profile-b"}
  ],
  "outboxMaxBytes": 134217728,
  "pageLimit": 20
}
```

Use a real HTTPS origin and keep each bearer token private. The sample values are placeholders. The relay rejects redirects so credentials cannot be forwarded to another host. One process owns all configured connector identities and serializes polling and native actions across them. Run with `python3 device_runtime.py /path/to/private-config.json`.

## Adapter process contract

The relay invokes the configured executable directly, without a shell. Each invocation gets one UTF-8 JSON request on stdin and must write exactly one UTF-8 JSON object to stdout. Diagnostics belong on stderr. Requests are bounded by a timeout.

`scan` requests also include a connector-specific `mediaDirectory` and `maxMediaBytes`, the remaining connector outbox byte budget for staged images. The adapter may return at most 20 image attachments per message with `{externalId,fileName,mimeType,sizeBytes,sha256,stagingKey}` after atomically writing each completed file under that directory. A staging key is a single filename matching `^[A-Za-z0-9][A-Za-z0-9._-]{0,179}$`; it cannot contain a path. The runtime checks the file type, size, and SHA-256 with 64 KiB reads, then streams uploads in 64 KiB chunks. It counts image bytes in the durable outbox ceiling and commits source cursor and event metadata together. `stagingKey` stays local and is removed from cloud metadata. A lost upload or ingest response is retried with the same external attachment ID. The Worker ACK is accepted only after uploaded file metadata matches and the attachment is bound to the message. Repeated events with the same external ID and body may add uploaded attachments; conflicting metadata or content is rejected, and an attachment already bound elsewhere cannot move. Routine `group` + `background` messages, including image messages, use the Worker's isolated group-text-backups endpoint and remain outside `agent_queue`; image-only events use body `[图片]`. The sample outbox allows 64 MiB per connector with two connectors; a configured per-connector budget must fit the largest image to be accepted. Other events go to the normal event endpoint. `history` remains false in routine scans; historical import is not included in this runtime.

`send` request: `{"op":"send","profile":"profile-a","commandId":"...","idempotencyKey":"...","conversationExternalId":"...","body":"...","attachments":[]}`. Response success is `{"ok":true,"receipt":"..."}` with a nonempty receipt. A retryable failure must explicitly mean the native operation was not dispatched: `{"ok":false,"retryable":true,"dispatched":false,"error":"short_code"}`. A definite pre-dispatch refusal is `{"ok":false,"dispatched":false,"error":"short_code"}`. Ambiguous or dispatched-without-receipt outcomes are uncertain. A process restart after native invocation begins is treated as uncertain and is never automatically sent again. Set connector `receiveOnly` to `true` to register only `receive_text` capability and skip command polling until native send is validated; omitted or false preserves the send path. File sending is not advertised or supported by this minimal runtime.

## Runtime limits

The single process scans configured profiles sequentially, one page of at most 20 messages each, every 15 seconds while a known source sweep or conversation initialization remains pending, 60 seconds while active, and 300 seconds while idle. It polls commands at most every 15 seconds and only claims from a connector whose recent device scan succeeded, unless that connector has `receiveOnly: true`. Normal event responses with `suppressed > 0` do not acknowledge or remove the outbox record. Background group text and images use the Worker's dedicated backup endpoint and are removed only after successful attachment upload, message binding, and response. Network and startup failures use bounded exponential backoff up to 300 seconds. The outbox has a byte ceiling; pending records are drained before new scans, and a full queue stops collection so the source cursor cannot move past unspooled messages. Delivery sends one event per HTTPS request, rotates fairly across connectors, and removes a record only after a successful Worker response. A failed connector is skipped while other connectors continue draining. This bounds transient memory and preserves retries, but does not promise full historical coverage or source-side retention.

An optional launchd sample is provided in `launchd.plist.example`; replace every local path and confirm Python and the private adapter on the device before enabling it. The sample invokes the native runtime launcher first. It applies and verifies a finite 64 MB fatal memory cap on its own PID before exec, and stops if the kernel rejects it. A point-in-time iPad run confirmed the Python process still reported 64/64 MB after exec, with fatal attributes enabled; the receive-only job was running at 21 MiB RSS, 0% CPU, and empty logs. This validates startup and limit inheritance only, not long-term or background reliability. This package does not install or activate a background service automatically.
