# Native Frida session helper

This iOS arm64 command-line helper owns one bounded Frida client session to the Frida 16.3.3 server already listening on the same device at `127.0.0.1:27042`. It does not start a server, keep a background process alive, read app data by itself, or connect to a remote host. The caller supplies a PID and JavaScript that performs its explicitly authorized operation.

Builds target iOS 15.0 or newer. Run the `Build native Frida session helper` workflow manually, or let its narrowly scoped source-change trigger validate a helper change. The workflow verifies the official Frida 16.3.3 iOS arm64 devkit SHA-256 before linking it. The artifact contains the executable, its object file and source, build provenance, and Frida's upstream license notice; it is not committed to the repository.

## Invocation

Provide exactly one script source. A path is useful for a local file; stdin is intended for a wrapper that streams the script and closes stdin.

```sh
native-frida-helper --pid 1234 --script /path/to/authorized-script.js
cat authorized-script.js | native-frida-helper --pid 1234 --stdin
```

The opt-in `--eternalize` flag changes only post-result cleanup. After the script returns its first valid JSON result, the helper asks Frida to eternalize that script, then detaches its session and closes the device manager without unloading the script. The helper reports `scriptLifetime: "eternalized"` only when Frida confirms that transition. If setup, result validation, or eternalization fails, the helper follows the normal bounded unload path. The default remains normal unload. An eternalized script remains in the target process until that process exits; this flag does not provide a command channel to the script.

After successful eternalization, the helper posts the script message `{ "type": "native-helper-eternalized" }` before detaching the session. A script that must register persistent callbacks can first register `recv('native-helper-eternalized', callback)`, send its prepared result, and publish callback-backed native pointers only from that acknowledgement callback. The event is never posted when eternalization fails.

`--timeout-ms` optionally sets the input-read and connect/attach/load/result deadline from 1000 through 120000 ms; the default is 30000 ms. Input JavaScript and the serialized Frida envelope are each limited to 1 MiB. The accepted result payload is capped slightly lower to leave room for the JSON envelopes, and final stdout is also capped at 1 MiB. Only the first valid `send` is retained; later messages cannot replace it. The helper uses asynchronous Frida operations with cancellation. By default it unloads the script, detaches the session, and closes the device manager; `--eternalize` replaces only the unload step after a valid result. Cleanup has its own bounded deadline; if a Frida callback does not return even after cancellation, the process exits and reports `cleanupIncomplete` so the caller can discard that invocation.

The script must send one JSON-serializable result with Frida's `send(value)`. The helper treats the first `send` as the completed result and returns one JSON object on stdout. It does not expose script text, Frida log messages, or script error details. Failures identify a stable stage and code. `dispatch` is `not_started` only when script loading has not begun; after loading begins without a returned result it is `unknown`.

For one bounded binary result, pass both `--binary-output-fd <fd>` and `--max-binary-bytes <bytes>`. The inherited descriptor must be greater than 2 and refer to an empty regular file opened for writing at offset zero. The maximum is from 1 byte through 50 MiB. The script sends one JSON payload with `ok: true` and an integer `byteCount`, plus the raw bytes as Frida's second `send` argument:

```javascript
send({ ok: true, byteCount: imageBytes.byteLength }, imageBytes);
```

`imageBytes` must be an `ArrayBuffer`.

The declared count must match the non-empty binary attachment. With binary output enabled, a send without bytes, an invalid count, a second observed send, or a failed write fails closed; the helper truncates the descriptor on failure and never writes the image bytes to stdout. Without both flags, a Frida message carrying binary data is rejected. A successful response retains the payload at `result` and adds `binaryWritten: true` and `binaryByteCount`; callers must also verify the descriptor size against both counts before accepting the file.

## Device installation

Install the executable in the jailbreak's program directory, not under a user library or application-data directory:

```sh
install_dir=/var/jb/usr/local/libexec/message-center
mkdir -p "$install_dir"
cp native-frida-helper "$install_dir/native-frida-helper"
chmod 755 "$install_dir/native-frida-helper"
```

Keep adapter status, queues, and databases under `/var/mobile/Library/` with the adapter's normal ownership and permissions. The helper is stateless and does not read or write that data directory.

Successful output has the form `{"ok":true,"stage":"complete","dispatch":"confirmed","result":...}`. An attach error has the form `{"ok":false,"stage":"attach","code":"attach_failed","dispatch":"not_started"}`. A timeout while waiting for the script result reports stage `await_result` and dispatch `unknown`.

Exit code is zero only when a result was received and cleanup completed. Any other exit code indicates an error or incomplete cleanup. Diagnostics never include the supplied script or returned message content.
