"""Parsed document models."""

from __future__ import annotations

from pydantic import BaseModel, HttpUrl


class ParsedDocument(BaseModel):
    """A cleaned, readable representation of a fetched web page."""

    url: HttpUrl
    title: str | None = None
    text: str
    content_type: str | None = None
