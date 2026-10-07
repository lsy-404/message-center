# Findings

- Source IDs are opaque equality tokens; cursor transitions do not order or compare them numerically or lexicographically.
- The source adapter must return pages in the verified native ordering and set `more=true` only when a known conversation initialization or bounded source sweep remains pending.
- A continuation page must not contain the frozen sweep head after its inclusive anchor. Reappearance indicates a looping or misdirected native page and is rejected without cursor advancement.
- The relay checks connectors sequentially. Setting the next scan interval to 15 seconds while `more` is true bounds delay between known pending pages; otherwise active and idle intervals remain 60 and 300 seconds.
