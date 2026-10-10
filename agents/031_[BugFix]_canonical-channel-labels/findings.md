# Findings

The navigation derives filter ids and counts from `channelLabel(conversation)`, while filtered rows use the same helper through `getChannelLabel`. Connector detail actions also create channel-filter ids with that helper. The helper currently returns profile and connector labels as free-form strings. Canonicalizing only the known QQ and WeChat aliases at this boundary will merge duplicate display/filter buckets while leaving connector ids, conversation ids, kinds, and external identities unchanged.

The pure `filterConversations` utility also supports callers without `getChannelLabel`, so its fallback value and selected filter value must use the same canonicalization rule. Unknown labels must retain their original value exactly; only recognized aliases should be rewritten.
