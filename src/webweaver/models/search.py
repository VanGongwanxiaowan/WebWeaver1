"""Search-related models."""

from __future__ import annotations

from pydantic import BaseModel, HttpUrl


class SearchResult(BaseModel):
    """A single web search result item."""

    title: str | None = None
    snippet: str | None = None
    url: HttpUrl
    source: str
    rank: int
