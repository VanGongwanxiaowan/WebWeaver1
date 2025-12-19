"""Evidence bank (Memory Bank).

This component is the authoritative store for source-grounded evidence collected during planning.
It is intentionally persistence-friendly and designed to be swapped with a DB-backed
implementation later.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
import re

from pydantic import TypeAdapter

from webweaver.logging import get_logger
from webweaver.models.evidence import Evidence, EvidenceItem, EvidenceSource
from webweaver.utils.ids import format_evidence_id

logger = get_logger(__name__)


@dataclass(frozen=True)
class EvidenceBankPaths:
    """Filesystem layout for an evidence bank."""

    root: Path

    @property
    def evidence_jsonl(self) -> Path:
        return self.root / "evidence.jsonl"

    @property
    def raw_dir(self) -> Path:
        return self.root / "raw"


class EvidenceBank:
    """In-memory evidence bank with append-only JSONL persistence."""

    def __init__(self, root_dir: Path) -> None:
        self._paths = EvidenceBankPaths(root=root_dir)
        self._paths.root.mkdir(parents=True, exist_ok=True)
        self._paths.raw_dir.mkdir(parents=True, exist_ok=True)

        self._evidences: dict[str, Evidence] = {}
        self._content_hash_to_id: dict[str, str] = {}
        self._next_id = 1

        self._load_existing()

    def _load_existing(self) -> None:
        if not self._paths.evidence_jsonl.exists():
            return

        adapter = TypeAdapter(Evidence)
        for line in self._paths.evidence_jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            ev = adapter.validate_python(data)
            self._evidences[ev.evidence_id] = ev
            if ev.content_hash:
                self._content_hash_to_id[ev.content_hash] = ev.evidence_id

            try:
                n = int(ev.evidence_id.split("_")[-1])
                self._next_id = max(self._next_id, n + 1)
            except Exception:  # pragma: no cover
                continue

        logger.info("Loaded %d evidences from %s", len(self._evidences), self._paths.evidence_jsonl)

    def add(
        self,
        *,
        query: str,
        source: EvidenceSource,
        summary: str,
        evidence_items: list[EvidenceItem],
        raw_text: str | None,
        tags: list[str] | None = None,
    ) -> Evidence:
        """Add a new evidence record to the bank.

        Deduplication is performed based on content hash of `(url + raw_text)` when raw_text exists.

        Args:
            query: Search query that led to this source.
            source: Source metadata.
            summary: Query-relevant summary.
            evidence_items: Extracted evidence items.
            raw_text: Optional full cleaned text; if provided, will be stored under `raw/`.
            tags: Optional tags.

        Returns:
            The stored Evidence.
        """

        content_hash = None
        raw_text_ref = None

        if raw_text:
            content_hash = self._hash_content(str(source.url), raw_text)
            existing_id = self._content_hash_to_id.get(content_hash)
            if existing_id:
                return self._evidences[existing_id]

            raw_text_ref = self._store_raw_text(content_hash, raw_text)

        evidence_id = format_evidence_id(self._next_id)
        self._next_id += 1

        ev = Evidence(
            evidence_id=evidence_id,
            query=query,
            source=source,
            summary=summary,
            evidence_items=evidence_items,
            raw_text_ref=raw_text_ref,
            content_hash=content_hash,
            tags=list(tags or []),
        )

        self._evidences[evidence_id] = ev
        if content_hash:
            self._content_hash_to_id[content_hash] = evidence_id

        self._append_jsonl(ev)
        return ev

    def get(self, evidence_id: str) -> Evidence:
        """Get an evidence by id."""

        return self._evidences[evidence_id]

    def bulk_get(self, evidence_ids: Iterable[str]) -> list[Evidence]:
        """Get evidences in order, ignoring missing ones."""

        out: list[Evidence] = []
        for eid in evidence_ids:
            ev = self._evidences.get(eid)
            if ev is not None:
                out.append(ev)
        return out

    def list_all(self) -> list[Evidence]:
        """List all evidences."""

        return list(self._evidences.values())

    def count(self) -> int:
        """Return evidence count."""

        return len(self._evidences)

    def stats(self) -> dict[str, int]:
        """Return basic stats."""

        return {"evidence_count": len(self._evidences)}

    def retrieve_scored(self, *, query: str, top_k: int) -> list[tuple[Evidence, int]]:
        """Retrieve evidences relevant to query, with a deterministic integer score."""

        tokens = _tokenize(query)
        if not tokens:
            return []

        scored: list[tuple[int, Evidence]] = []
        for ev in self._evidences.values():
            hay = " ".join(
                [
                    ev.query,
                    str(ev.source.title or ""),
                    str(ev.source.publisher or ""),
                    ev.summary,
                    " ".join([it.content for it in ev.evidence_items]),
                ]
            )
            score = _score(tokens, hay)
            if score <= 0:
                continue
            scored.append((score, ev))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [(ev, score) for score, ev in scored[:top_k]]

    def retrieve(self, *, query: str, top_k: int) -> list[Evidence]:
        """Retrieve evidences relevant to query."""

        return [ev for ev, _score in self.retrieve_scored(query=query, top_k=top_k)]

    def _append_jsonl(self, ev: Evidence) -> None:
        payload = ev.model_dump(mode="json")
        line = json.dumps(payload, ensure_ascii=False)
        with self._paths.evidence_jsonl.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _store_raw_text(self, content_hash: str, raw_text: str) -> str:
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        p = self._paths.raw_dir / f"{ts}_{content_hash[:12]}.txt"
        p.write_text(raw_text, encoding="utf-8")
        return str(p.relative_to(self._paths.root))

    @staticmethod
    def _hash_content(url: str, text: str) -> str:
        h = hashlib.sha256()
        h.update(url.encode("utf-8"))
        h.update(b"\n")
        h.update(text.encode("utf-8"))
        return h.hexdigest()


_WORD_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in _WORD_RE.findall(text) if len(t) >= 2}


def _score(tokens: set[str], text: str) -> int:
    hay = text.lower()
    s = 0
    for t in tokens:
        if t in hay:
            s += 1
    return s
