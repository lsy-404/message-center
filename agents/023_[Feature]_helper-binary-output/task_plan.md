# Helper binary output

## Scope

Add an opt-in, bounded binary attachment path to the existing native Frida helper. The inherited descriptor must be a regular, empty, writable file at offset zero. JSON mode remains unchanged; binary mode accepts one Frida send with declared byte count matching its raw attachment, writes at most 50 MiB, and reports only fixed metadata plus the JSON payload.

## Constraints

- No device or cloud operation in this task.
- No private adapter source, selectors, credentials, or payloads in the public repository.
- Keep stdout free of binary bytes; clear partial output on failure.
- Validate descriptor parsing and writes with host C tests; iOS helper build remains CI-owned.

## Verification

Run root tests, especially native helper contract and the host C binary-output test. Inspect workflow artifact inputs and provenance for the added source/header.
