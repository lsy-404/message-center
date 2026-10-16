# Findings

- UI sticker presentation is now driven only by `attachment.presentation === "sticker"` and image MIME; filename and body text do not classify images. Ordinary image rendering retains its existing 440×420 box; stickers are capped visually at 160×160 CSS pixels.
- The existing inbound upload route has a 50 MiB byte cap. The Worker now rejects mismatched metadata and verifies streamed byte count plus the R2 object's size/SHA-256. This is an inbound file boundary, independent of the sticker CSS dimensions; no global outbound media cap was added.
- Public attachment metadata previously clipped invalid sizes and discarded non-array/over-count lists. It now rejects malformed metadata and preserves only the explicit `sticker` presentation for images.
- Event attachment `sizeBytes` must be a JSON number and safe integer; booleans and numeric strings are rejected. The HTTP upload `Content-Length` remains parsed from its required string header.
- Quote preview is a top-level `reply` object with `sourceText`, `sourceTextTruncated`, and `sourceExpired`. Expired source text is rejected at ingestion and suppressed at display. The quoted source stays outside `body`.
- QQ UI fixture capabilities remain `receive_text` only, and the attachment composer stays disabled. No public sticker-send contract is supported by verified native evidence.
- The private counterpart confirms the current native source still does not emit an image-bearing sticker discriminator. UI and public contract behavior are validated synthetically; actual native sticker discovery/rendering still needs device evidence.
- Cloudflare R2 Worker API docs confirm `put()` returns an R2 object with `size` and SHA-256 checksums, and `head()` exposes the same checksum data. The fake R2 test implements that contract.
- A production upload exposed a runtime constraint not represented by the previous mock: R2 rejects arbitrary transformed ReadableStreams because they do not carry a known length. Cloudflare's official `FixedLengthStream` API supplies a declared length and errors when too few or too many bytes flow through it. The existing pre-upload 50 MiB metadata gate bounds that length.
# Canonical R2 repair follow-up

- A concurrent insert can leave the request with a temporary upload object and a canonical database row bound to the same connector, external ID, conversation, filename, MIME type, byte length, and SHA-256.
- Repair is authorized only when that complete row binding matches the current request. A canonical R2 object counts as valid only when HEAD reports the expected byte length and SHA-256.
- If put returns ambiguous or mismatched metadata, reconcile with HEAD and accept only exact expected size plus SHA-256. Never delete the canonical key; a confirmed mismatch may be overwritten from the separately verified temporary upload, while HEAD failures leave the temporary upload for retry. Temporary cleanup happens only after canonical acceptance.
