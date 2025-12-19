"""Outline models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Outline(BaseModel):
    """A report outline.

    In the first milestone, we store outline as markdown text containing `<citation>id_1,id_2</citation>`.
    Later iterations can upgrade this to an AST.
    """

    text: str
    version: int = Field(default=1, ge=1)
