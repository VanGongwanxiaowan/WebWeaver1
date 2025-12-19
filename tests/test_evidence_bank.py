"""Tests for EvidenceBank."""

from __future__ import annotations

from pathlib import Path

from webweaver.memory.evidence_bank import EvidenceBank
from webweaver.models.evidence import EvidenceItem, EvidenceSource


def test_evidence_bank_deduplicates_by_content_hash(tmp_path: Path) -> None:
    """It should deduplicate same (url + raw_text) insertions."""

    bank = EvidenceBank(tmp_path)
    source = EvidenceSource(url="https://example.com", title="Example")

    ev1 = bank.add(
        query="q1",
        source=source,
        summary="s1",
        evidence_items=[EvidenceItem(type="quote", content="a")],
        raw_text="raw",
        tags=["t"],
    )
    ev2 = bank.add(
        query="q2",
        source=source,
        summary="s2",
        evidence_items=[EvidenceItem(type="quote", content="b")],
        raw_text="raw",
        tags=["t"],
    )

    assert ev1.evidence_id == ev2.evidence_id
    assert bank.count() == 1


def test_evidence_bank_persists_and_reload(tmp_path: Path) -> None:
    """It should persist to JSONL and reload previously written evidences."""

    bank1 = EvidenceBank(tmp_path)
    source = EvidenceSource(url="https://example.com", title="Example")

    ev1 = bank1.add(
        query="q",
        source=source,
        summary="s",
        evidence_items=[],
        raw_text="raw",
        tags=[],
    )

    bank2 = EvidenceBank(tmp_path)
    assert bank2.count() == 1
    assert bank2.get(ev1.evidence_id).source.url == source.url
