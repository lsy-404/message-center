# Findings

- Runtime command alias parsing required `<profile>:<alias>`, but the Worker command builder passes the stored conversation `external_id` unchanged.
- QQ adapter `_message_event` and `_conversation_profile` emit the raw canonical alias, and Worker ingestion stores it unchanged.
- `Relay` consumes the connector list directly from config; each connector's `profile` is a scalar string. There is no `normalize_connectors` stage in the device runtime.
- The command parser now accepts only the raw canonical conversation alias; profile scoping remains supplied by the selected connector and `(connector_id, profile)` cursor lookup.
- The end-to-end host regression invokes `process_command` with the raw Worker-shaped alias and verifies the confirmed receipt registers the priority entry on the current cursor.
- Focused runtime validation passed: 106 tests, 2 platform skips.
