"""Event model used for streaming output and replay.

The workflow produces a sequence of events. Events are recorded to JSONL so the run can be
replayed later (e.g., for debugging, audits, or UI playback).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """High-level event categories."""

    SYSTEM = "system"
    TOOL = "tool"
    LLM = "llm"
    ERROR = "error"


class ContentType(str, Enum):
    """Semantic types within event streams."""

    MESSAGE = "message"

    # Planning
    PLANNER_STEP = "planner_step"
    SEARCH_QUERY = "search_query"
    SEARCH_RESULTS = "search_results"
    URL_SELECTED = "url_selected"
    EVIDENCE_ADDED = "evidence_added"
    OUTLINE_UPDATED = "outline_updated"
    PLANNER_TERMINATE = "planner_terminate"

    # Evaluation
    OUTLINE_JUDGE_RESULT = "outline_judge_result"

    # Writing
    WRITER_SECTION_START = "writer_section_start"
    WRITER_SECTION_DONE = "writer_section_done"
    WRITER_STEP = "writer_step"
    WRITER_RETRIEVE_QUERY = "writer_retrieve_query"
    WRITER_RETRIEVE_RESULTS = "writer_retrieve_results"
    WRITER_WRITE = "writer_write"
    WRITER_TERMINATE = "writer_terminate"
    REPORT_DONE = "report_done"


class RunEvent(BaseModel):
    """A single event in a run."""

    run_id: str
    seq: int = Field(ge=1)
    ts: datetime = Field(default_factory=datetime.utcnow)

    event_type: EventType
    content_type: ContentType

    data: str | dict | list | None = None
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
