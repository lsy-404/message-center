# Findings

Launchd cannot read the app-container media path with ordinary file open even when metadata checks pass. Inside the app, the existing native helper can read the bytes through the verified Foundation file API. Frida delivers binary `send` attachments as `GBytes`; the helper can write that attachment into a caller-owned inherited descriptor without exposing its bytes through stdout.

Public helper contract: both `--binary-output-fd FD` and `--max-binary-bytes N` are required together. FD must be greater than 2, refer to a regular empty writable file, and start at offset zero. N is 1..50 MiB. The script sends `{ok:true,byteCount:N}` plus one raw `ArrayBuffer`. Success JSON adds `binaryWritten:true` and `binaryByteCount:N`, preserving the payload at `result`; callers also verify the descriptor size equals both counts. Errors fail closed and truncate the descriptor. No second-send waiting protocol is added.

- Real iPad synthetic transfer wrote and returned four matching bytes, but boxing a `gboolean` expression produced numeric `binaryWritten:1`; the strict Python caller correctly rejected it. Use explicit Objective-C boolean constants and repeat the artifact/device test.
- The initial numeric `binaryWritten` mismatch was corrected to a strict boolean and installed. Bounded image export subsequently passed size and integrity checks. The validation-directory launch limitation was resolved through the allowlisted bootstrap executable path.
