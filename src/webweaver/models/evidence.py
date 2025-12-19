"""Evidence models.

This module defines the minimal, production-friendly schema for the WebWeaver "Memory Bank".
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


EvidenceType = Literal["quote", "data", "definition", "claim", "case"]


class EvidenceSource(BaseModel):
    """Metadata about where an evidence comes from."""

    url: HttpUrl
    title: str | None = None
    publisher: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)


class EvidenceItem(BaseModel):
    """A verifiable evidence unit extracted from a source."""

    type: EvidenceType
    content: str
    location: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class Evidence(BaseModel):
    """A source-level evidence record stored in the evidence bank."""

    evidence_id: str
    query: str
    source: EvidenceSource
    summary: str
    evidence_items: list[EvidenceItem] = Field(default_factory=list)

    raw_text_ref: str | None = None
    content_hash: str | None = None
    tags: list[str] = Field(default_factory=list)
