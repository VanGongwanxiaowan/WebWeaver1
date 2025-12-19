"""Base agent interfaces."""

from __future__ import annotations

from dataclasses import dataclass

from webweaver.llm.client import LLMClient


@dataclass(frozen=True)
class AgentContext:
    """Common context passed to agents."""

    query: str


class BaseAgent:
    """Base class for WebWeaver agents."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
