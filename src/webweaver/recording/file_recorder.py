"""File-based event recorder.

Records events to `events.jsonl` for replay.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from webweaver.events import RunEvent


@dataclass
class FileEventRecorder:
    """Append-only JSONL recorder."""

    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: RunEvent) -> None:
        """Append an event."""

        line = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def iter_events(path: Path) -> list[RunEvent]:
    """Load all events from a JSONL file."""

    events: list[RunEvent] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(RunEvent.model_validate_json(line))
    return events
