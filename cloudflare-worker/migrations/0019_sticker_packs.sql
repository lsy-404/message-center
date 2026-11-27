CREATE TABLE IF NOT EXISTS sticker_packs (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  position INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sticker_pack_images (
  id TEXT PRIMARY KEY,
  pack_id TEXT NOT NULL,
  object_key TEXT NOT NULL UNIQUE,
  file_name TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  position INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (pack_id) REFERENCES sticker_packs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sticker_pack_images_pack ON sticker_pack_images(pack_id, position);
