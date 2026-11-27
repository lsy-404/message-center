const IGNORED = /[\p{P}\p{S}\p{Z}\p{Cc}\p{Cf}️\p{Extended_Pictographic}]/gu;

export function normalizeContactName(value) {
  return String(value ?? "").normalize("NFKC").toLowerCase().replace(IGNORED, "");
}

// Suggestions group direct conversations whose normalized names match across at least two connectors.
// rows: { id, title, connectorId, contactId }; returns one suggestion per matching name key.
export function suggestContactMatches(rows, dismissedKeys = new Set()) {
  const groups = new Map();
  for (const row of rows) {
    const key = normalizeContactName(row.title);
    if ([...key].length < 2 || dismissedKeys.has(key)) continue;
    const group = groups.get(key) || [];
    group.push(row);
    groups.set(key, group);
  }
  const suggestions = [];
  for (const [key, group] of groups) {
    const unlinked = group.filter((row) => !row.contactId);
    const contactIds = [...new Set(group.map((row) => row.contactId).filter(Boolean))];
    if (!unlinked.length || contactIds.length > 1) continue;
    if (new Set(group.map((row) => row.connectorId)).size < 2) continue;
    suggestions.push({
      key,
      name: group[0].title,
      contactId: contactIds[0] || null,
      conversationIds: unlinked.map((row) => row.id),
    });
  }
  return suggestions;
}
