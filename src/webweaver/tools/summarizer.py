"""Query-relevant summarization."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from webweaver.llm.client import ChatMessage, LLMClient
from webweaver.prompts import SUMMARIZER_SYSTEM_PROMPT


@dataclass(frozen=True)
class Summarizer:
    """Generate a concise, query-relevant summary for a document."""

    llm: LLMClient

    def summarize(self, *, query: str, text: str) -> str:
        """Summarize document text relevant to query."""

        messages = [
            ChatMessage(
                role="system",
                content=SUMMARIZER_SYSTEM_PROMPT,
            ),
            ChatMessage(
                role="user",
                content=(
                    f"Query: {query}\n\n"
                    "Document:\n"
                    f"{text}\n\n"
                    "Return a concise summary (150-250 words)."
                ),
            ),
        ]
        return self.llm.complete(messages, temperature=0.2).strip()

    async def summarize_async(self, *, query: str, text: str) -> str:
        """Async variant of :meth:`summarize`.

        当前使用线程池 offload 阻塞 LLM 调用，避免阻塞事件循环。
        """

        return await asyncio.to_thread(self.summarize, query=query, text=text)
