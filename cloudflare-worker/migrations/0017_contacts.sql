CREATE TABLE IF NOT EXISTS contacts (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contact_conversations (
  conversation_id TEXT PRIMARY KEY,
  contact_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
  FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_contact_conversations_contact ON contact_conversations(contact_id);

CREATE TABLE IF NOT EXISTS contact_suggestion_dismissals (
  match_key TEXT PRIMARY KEY,
  created_at TEXT NOT NULL
);
