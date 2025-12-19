from __future__ import annotations

from dataclasses import dataclass

from webweaver.models.outline import Outline


@dataclass
class RunState:
    query: str
    outline: Outline | None = None
    planner_step_index: int = 0
    max_planner_steps: int = 0
    evidence_count: int = 0

    def snapshot(self) -> dict[str, str | int | None]:
        return {
            "query": self.query,
            "outline_version": self.outline.version if self.outline is not None else None,
            "planner_step_index": self.planner_step_index,
            "max_planner_steps": self.max_planner_steps,
            "evidence_count": self.evidence_count,
        }
