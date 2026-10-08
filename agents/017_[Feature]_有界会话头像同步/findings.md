# Findings

- Existing `conversation_profiles.py` sends each profile as an empty-body PUT and already refuses redirects. The Worker profile endpoint accepts raw image bytes with `Content-Length`, `x-content-sha256`, and PNG/JPEG/GIF/WebP magic validation, with a 2 MiB Worker-side cap.
- The device constraint is stricter: reject malformed base64 and validate every avatar in the full batch before opening the network; cap decoded bytes per image and across the batch at 128 KiB.
- Profiles without `avatarBase64` (or with an empty string) retain the metadata-only request behavior.
- Strict decoding requires ASCII canonical base64, validates the decoded format from magic bytes, and infers the matching content type. Decoded avatar bytes remain bounded across the whole prepared batch, so all validation completes before the opener is created.
- A dotted unittest module invocation did not resolve because the repository's root `test` directory is not a Python package; invoking the test file directly works. This was a test command issue, not a code failure.
