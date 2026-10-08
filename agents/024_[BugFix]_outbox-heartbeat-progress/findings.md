# Findings

- `pass_once()` attempts at most five `flush_one()` deliveries before scanning and heartbeats.
- `flush_one()` selects each row by its actual `connector_id`, verifies an acknowledged and unsuppressed response, deletes that row, and now returns that exact connector ID on success.
- When a connector still has pending outbox rows, `pass_once()` skips its scan. During backlog catch-up, the source freshness window can expire even while the relay successfully delivers events.
- Heartbeat state is derived from fresh source health or an acknowledged delivery for that connector during the current pass. Command polling independently uses source health and freshness and remains unchanged.
