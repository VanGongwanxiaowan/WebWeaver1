from __future__ import annotations

from pydantic import BaseModel, Field


class RetrieveAction(BaseModel):
    """Writer retrieve action.

    The writer can either:
    - issue a semantic/text query over the evidence bank, or
    - request specific evidence ids via ``citation_ids`` (which should match
      ``Evidence.evidence_id`` such as ``ev_0001``).

    If ``citation_ids`` is provided and non-empty, the runner will prioritize
    exact-id retrieval and ignore ``query`` for that step.
    """

    query: str | None = None
    top_k: int = Field(default=8, ge=1, le=50)
    citation_ids: list[str] | None = None


class WriteAction(BaseModel):
    text: str


class WriterTerminateAction(BaseModel):
    reason: str = ""
