# Device runtime

This Python 3.9 standard-library relay connects a device directly to the Message Center Worker over HTTPS. It does not require a desktop service, USB connection, or LAN connection. Vendor-specific device access stays in a private executable implementing the JSON contract below.

## Configuration

Store a UTF-8 JSON configuration at a private local path with mode `0600`. Relative adapter and database paths resolve from the configuration file directory:

```json
{
  "serviceUrl": "https://messages.example.invalid",
  "database": "./message-center.sqlite3",
  "adapter": "./private-device-adapter",
  "connectors": [
    {"id":"instance-device-primary","token":"injected-token-a",
     "kind":"im","accountLabel":"Account A","displayName":"Device relay A","profile":"profile-a",
     "receiveOnly":true},
    {"id":"instance-device-secondary","token":"injected-token-b",
     "kind":"im","accountLabel":"Account B","displayName":"Device relay B","profile":"profile-b"}
  ],
  "outboxMaxBytes": 16777216,
  "pageLimit": 20
}
```

Use a real HTTPS origin and keep each bearer token private. The sample values are placeholders. The relay rejects redirects so credentials cannot be forwarded to another host. One process owns all configured connector identities and serializes polling and native actions across them. Run with `python3 device_runtime.py /path/to/private-config.json`.

## Adapter process contract

The relay invokes the configured executable directly, without a shell. Each invocation gets one UTF-8 JSON request on stdin and must write exactly one UTF-8 JSON object to stdout. Diagnostics belong on stderr. Requests are bounded by a timeout.

`scan` request: `{"op":"scan","profile":"profile-a","cursor":null,"limit":20,"maxBytes":921600,"maxEventBytes":262144,"history":false}`. The adapter must paginate by both `limit` and the supplied byte budgets, counting the serialized response envelope and cursor against `maxBytes`, and the full `{connectorId,messages:[event]}` envelope against `maxEventBytes`; the runtime independently rejects responses above 900 KiB and events above 256 KiB before committing the cursor. Response: `{"ok":true,"health":"online","active":true,"more":false,"cursor":"opaque-next-cursor","messages":[...]}`. Every message must be a normalized Worker event with stable `externalId`, `conversationExternalId`, `conversationTitle`, `senderName`, `occurredAt`, and optional `body`, `senderId`, `contentType`, `conversationType`, `trigger`, `mentioned`, `context`, and `placement`. Cursor values are opaque JSON and are stored transactionally with the durable outbox records. `more` is a strict boolean signal that another scan is already needed, such as when known conversations remain uninitialized or a source sweep is unfinished; it selects a 15-second interval. Otherwise `active` selects 60 seconds and idle uses 300 seconds. Routine `group` + `background` events must contain nonempty text of at most 20,000 UTF-16 code units and no attachments; these are routed to the Worker's group-text-backups endpoint. Other events go to the normal event endpoint. `history` remains false in routine scans; historical import is not included in this runtime. This initial implementation accepts text events only; a page containing attachments is rejected before its cursor is committed.

`send` request: `{"op":"send","profile":"profile-a","commandId":"...","idempotencyKey":"...","conversationExternalId":"...","body":"...","attachments":[]}`. Response success is `{"ok":true,"receipt":"..."}` with a nonempty receipt. A retryable failure must explicitly mean the native operation was not dispatched: `{"ok":false,"retryable":true,"dispatched":false,"error":"short_code"}`. A definite pre-dispatch refusal is `{"ok":false,"dispatched":false,"error":"short_code"}`. Ambiguous or dispatched-without-receipt outcomes are uncertain. A process restart after native invocation begins is treated as uncertain and is never automatically sent again. Set connector `receiveOnly` to `true` to register only `receive_text` capability and skip command polling until native send is validated; omitted or false preserves the send path. File sending is not advertised or supported by this minimal runtime.

## Runtime limits

The single process scans configured profiles sequentially, one page of at most 20 messages each, every 15 seconds while a known source sweep or conversation initialization remains pending, 60 seconds while active, and 300 seconds while idle. It polls commands at most every 15 seconds and only claims from a connector whose recent device scan succeeded, unless that connector has `receiveOnly: true`. Normal event responses with `suppressed > 0` do not acknowledge or remove the outbox record. Background group text uses the Worker's dedicated backup endpoint and is removed only after a successful response. Network and startup failures use bounded exponential backoff up to 300 seconds. The outbox has a byte ceiling; pending records are drained before new scans, and a full queue stops collection so the source cursor cannot move past unspooled messages. Delivery sends one event per HTTPS request, rotates fairly across connectors, and removes a record only after a successful Worker response. A failed connector is skipped while other connectors continue draining. This bounds transient memory and preserves retries, but does not promise full historical coverage or source-side retention.

An optional launchd sample is provided in `launchd.plist.example`; replace every local path and confirm Python and the private adapter on the device before enabling it. This package does not install or activate a background service automatically.
