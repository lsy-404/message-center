# Findings

- Background group events without `isSelf: true` retain the legacy group-text-backup route and its text-only validation.
- Self-authored group events use normal event ingestion, which records outbound/delivered direction and supports staged attachment metadata.
- The legacy backup endpoint now rejects self-authored records before processing attachment references, preventing an outbound event from becoming an inbound backup.
- Runtime input rejects non-boolean `isSelf` values before cursor commit.
