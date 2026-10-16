# Findings

## Result

No blocking issue remains in the reviewed public contract at candidate `d50933f831e5d35cbe58815fa5466fd9cfbd9505` (based on `ac7ccd30f78275c33875fba69dee5f6606caa89f`). The added marker is an exact `system` literal. The Worker derives connector kind from its authenticated database row and accepts the marker only for QQ inbound events with `isSelf: false`, nonempty text content, and no attachments; caller-supplied metadata cannot create the marker. System rows bypass group-background suppression, do not enter new agent queues, and are filtered from listen, claim-by-ID, next-message, and reply paths. The atomic reply insertion rechecks the leased source row so an upgrade racing after the reply pre-read cannot create a command.

The legacy duplicate upgrade is narrowly scoped to the same connector/external ID/conversation, an inbound text row whose exact body is `[类型:8]`, no linked attachments, and no attachment metadata. Its SQL compare-and-swap checks the original `metadata_json` snapshot as well as the old body and target; a metadata-only attachment write between read and update causes a conflict. The update changes only body, text content type, and metadata, leaving canonical message ID, sender ID/name, direction, timestamps, delivery state, and queue class intact. Worker tests cover cross-target and ordinary-body conflicts, concurrent attachment metadata, wrong connector, self/outbound marker rejection, old queued rows, and an active lease followed by upgrade and reply attempt.

The active production runtime is `bridge/device-runtime/device_runtime.py`. It validates the marker before accepting a scan page, requiring QQ driver, explicit `isSelf: false`, nonempty bounded text content, and no attachments; marked rows route to normal events, while other background group messages retain the backup route. Scan results are serialized into the durable outbox without dropping fields, and route-aware batching keeps mixed endpoints separated. A local synthetic scan-to-outbox-to-route check confirmed marker preservation. The unused TypeScript `DeviceSessionAdapter` does not forward the marker because its profile identity cannot prove a QQ driver; it stays fail-closed and is not the deployed iPad path.

The API projects `presentation: system` only from stored metadata on inbound QQ text rows with a nonempty body and no attachments. The UI renders that explicit marked content as centered plain text and omits the sender name/avatar; unmarked ordinary text and `[类型:8]` continue through the normal message row. Browser coverage is synthetic.

## Limits

This public patch does not prove that the private native QQ producer sets the marker only from the verified raw system-sender identity. In particular, do not infer identity zero from a hashed sender alias. Until the private producer emits `presentation: system` from its verified native evidence, no live system rows will receive this presentation. No device or cloud execution was performed.

## Code locations

- `bridge/device-runtime/device_runtime.py:96, 898-916`: endpoint selection and strict marker validation.
- `cloudflare-worker/worker/index.js:166-207, 1336-1357`: connector/direction validation, suppression exception, and canonical metadata persistence.
- `cloudflare-worker/worker/index.js:1419-1473`: exact duplicate predicate, metadata snapshot CAS, and race winner verification.
- `cloudflare-worker/worker/index.js:1958-1974, 2838-2990`: safe inbox projection and queue/reply exclusions.
- `cloudflare-worker/ui/src/App.vue:285-300, 1427-1444`: explicit inbound rendering and hidden sender identity.
- `test/test_device_runtime.py:1288-1352`, `test/worker-schema.test.mjs:1996-2345`, `test/ui-navigation-media.cjs:47-117`: route, validation, race, persistence, and UI coverage.