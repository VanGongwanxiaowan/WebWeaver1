"""Tests for citation parsing utilities."""

from __future__ import annotations

from webweaver.utils.citations import extract_citation_ids, strip_citation_tags


def test_extract_citation_ids_ordered_dedup() -> None:
    """It should extract ids from multiple tags and keep first-seen order."""

    text = (
        "Intro <citation>id_1, id_2</citation> mid <citation>id_2,id_3</citation> end"
    )
    assert extract_citation_ids(text) == ["id_1", "id_2", "id_3"]


def test_strip_citation_tags() -> None:
    """It should remove citation tags but keep surrounding content."""

    text = "Hello <citation>id_1</citation> world"
    assert strip_citation_tags(text).strip() == "Hello  world"
