# Findings

- The helper retains the first valid script `send` as the result and only requests eternalization when `--eternalize` is set. Eternalization failure returns through cleanup before the success flag is set.
- Runtime verification showed that posting after successful eternalization does not deliver a message to the script. The static API declaration and source-order assertions were insufficient to establish a live control channel.
- The unsupported post, handshake documentation, and test expectation were removed. The ordinary helper path and verified eternalized cleanup behavior remain unchanged.
- Any replacement handshake must be validated at runtime before callback pointers are published. Keep private application details out of this public helper.
