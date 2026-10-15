-- Per-connector and per-conversation AI access overrides (visible, push,
-- commands, reply) layered over built-in defaults, plus internal read marks.
ALTER TABLE connector_instances
  ADD COLUMN agent_settings_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE conversations
  ADD COLUMN agent_settings_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE messages
  ADD COLUMN owner_read_at TEXT;

ALTER TABLE messages
  ADD COLUMN agent_read_at TEXT;
