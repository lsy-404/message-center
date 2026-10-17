# Findings

- A pending native QQ image event has valid uploaded bytes and an explicit structured reply. Cloud upload returns200, then group-backup ingestion returns message_external_id_conflict. The existing cloud message has the exact prior body prefix followed by the same image placeholder, same time and image digest. No native sender dispatch occurred.
- Group backups currently reject any stored body change and omit reply normalization. Ordinary events validate structured replies but reject exact quote-marker removal on existing immediate records. Quote enrichment must be identity-scoped and must not permit arbitrary body replacement or cross-conversation binding.
- The public runtime separately blocks all reads when any outbox row exists. A delegated isolated change separates bounded delivery backoff from source reads while preserving capacity and atomic cursor/outbox commits.
