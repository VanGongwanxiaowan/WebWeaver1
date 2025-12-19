"""Citation parsing and rendering."""

from __future__ import annotations

import re

_CITATION_RE = re.compile(r"<citation>(?P<ids>[^<]+)</citation>", re.IGNORECASE)


def extract_citation_ids(text: str) -> list[str]:
    """Extract evidence ids from `<citation>...</citation>` tags.

    Args:
        text: Text that may include one or more citation tags.

    Returns:
        List of ids like `id_1`.
    """

    ids: list[str] = []
    for m in _CITATION_RE.finditer(text):
        raw = m.group("ids")
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        ids.extend(parts)
    # De-duplicate while keeping order
    seen: set[str] = set()
    out: list[str] = []
    for x in ids:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def strip_citation_tags(text: str) -> str:
    """Remove citation tags from text."""

    return _CITATION_RE.sub("", text)
