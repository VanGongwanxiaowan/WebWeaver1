"""OpenAI-compatible LLM client.

This wraps the `openai` Python SDK and provides a minimal interface for chat completions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Sequence

from openai import OpenAI

from webweaver.config import Settings
from webweaver.logging import get_logger

logger = get_logger(__name__)

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    """A chat message."""

    role: Role
    content: str


class LLMClient:
    """LLM client using OpenAI-compatible Chat Completions API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        if not settings.openai_api_key:
            raise ValueError(
                "Missing WEBWEAVER_OPENAI_API_KEY. "
                "Set it in environment variables or a .env file."
            )

        self._client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)

    def complete(self, messages: Sequence[ChatMessage], *, temperature: float = 0.2) -> str:
        """Generate a completion.

        Args:
            messages: Chat messages.
            temperature: Sampling temperature.

        Returns:
            Assistant message content.
        """

        payload: list[dict[str, str]] = [{"role": m.role, "content": m.content} for m in messages]
        resp = self._client.chat.completions.create(
            model=self._settings.openai_model,
            messages=payload,
            temperature=temperature,
            timeout=self._settings.openai_timeout_s,
        )
        choice = resp.choices[0]
        if not choice.message or choice.message.content is None:
            return ""
        return choice.message.content

    @staticmethod
    def format_messages(messages: Iterable[Mapping[str, Any]]) -> list[ChatMessage]:
        """Convert plain dict messages to ChatMessage."""

        out: list[ChatMessage] = []
        for m in messages:
            out.append(ChatMessage(role=m["role"], content=m["content"]))
        return out
