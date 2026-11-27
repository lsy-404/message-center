ALTER TABLE conversation_profiles ADD COLUMN is_muted INTEGER NOT NULL DEFAULT 0 CHECK(is_muted IN (0, 1));
