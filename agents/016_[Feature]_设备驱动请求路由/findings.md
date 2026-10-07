# Findings: Device Driver Request Routing

- The public runtime currently omits connector `kind` from both adapter operations. The connector is already selected before scan and after command lease plus ledger creation before send.
- Runtime scan event/profile IDs must consistently include `<profile>:conversation-<8 hex>` so the cloud command target can be strictly scoped to the connector profile.
- The command payload names the canonical conversation `externalConversationId` and `body`. The adapter must parse only that canonical ID, not accept a raw alias or a peer identifier.
- Send outcomes need to match the public runtime's existing branch contract: confirmed `{ok:true, receipt:string}`; safe pre-dispatch failure `{ok:false, dispatched:false, retryable:true|false}`; uncertain `{ok:false, dispatched:true, retryable:false}`.
- A command is authorized only after lease acquisition and durable `started` ledger entry. Runtime passes explicit `confirmed` and `targetConfirmed` flags at that point; no additional device UI confirmation is appropriate.
- WeChat send remains disabled because successful native send status has not been verified.
