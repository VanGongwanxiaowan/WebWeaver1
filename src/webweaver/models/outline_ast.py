from __future__ import annotations

from pydantic import BaseModel, Field


class OutlineNode(BaseModel):
    """Structured outline node.

    This is the internal, machine-readable representation suggested in plan.md (Outline AST).
    """

    id: str
    title: str
    level: int = Field(ge=1, le=6)

    bullets: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)

    children: list["OutlineNode"] = Field(default_factory=list)


class OutlineAST(BaseModel):
    root_title: str = "Report"
    nodes: list[OutlineNode] = Field(default_factory=list)
