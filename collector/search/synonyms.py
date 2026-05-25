"""
Query-side synonym expansion for The Collector's search engine.

Design notes
------------
- Hand-curated only. No WordNet, no auto-generation.
  WordNet is too broad; "tank" → military vehicle ≠ fish tank.
- Bidirectional by convention: if A maps to B, B should map to A.
- Keep this list small (< 50 entries). If it grows beyond that, consider
  migrating to a Postgres TEXT SEARCH DICTIONARY with a .syn file instead,
  which handles synonyms at index time and avoids query rewriting.
- Synonyms expand at query time, not index time, so adding entries here
  takes effect immediately with no re-indexing.
"""
from __future__ import annotations

SYNONYMS: dict[str, list[str]] = {
    # --- food / cooking ---
    "chickpea": ["garbanzo"],
    "garbanzo": ["chickpea"],

    # --- web terminology ---
    "webpage": ["website", "homepage"],
    "website": ["webpage", "homepage"],
    "homepage": ["webpage", "website"],

    # --- old-web proper nouns (common typos as bidirectional synonyms) ---
    "geocities": ["geociteis"],
    "geociteis": ["geocities"],
    "neocities": ["neociteis"],
    "neociteis": ["neocities"],
}


def expand(word: str) -> list[str]:
    """
    Return the word plus all known synonyms, lowercased and deduplicated.
    Always includes the original word first.

    >>> expand("garbanzo")
    ['garbanzo', 'chickpea']
    >>> expand("unknownword")
    ['unknownword']
    """
    w = word.lower()
    seen: set[str] = {w}
    result = [w]
    for syn in SYNONYMS.get(w, []):
        s = syn.lower()
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result
