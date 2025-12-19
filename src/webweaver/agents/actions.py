"""Agent action types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchAction:
    """Planner requests evidence acquisition."""

    queries: list[str]
    goal: str


@dataclass(frozen=True)
class WriteOutlineAction:
    """Planner provides an outline update."""

    outline_text: str


@dataclass(frozen=True)
class TerminateAction:
    """Planner terminates planning."""

    reason: str


PlannerAction = SearchAction | WriteOutlineAction | TerminateAction
