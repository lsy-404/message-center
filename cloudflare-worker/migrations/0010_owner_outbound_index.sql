CREATE INDEX IF NOT EXISTS idx_messages_owner_outbound ON messages(occurred_at) WHERE direction = 'outbound';
CREATE INDEX IF NOT EXISTS idx_messages_owner_outbound_conversation ON messages(conversation_id, occurred_at) WHERE direction = 'outbound';
