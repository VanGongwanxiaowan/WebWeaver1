"""Evidence extraction.

The extractor returns verifiable items (quotes, data points, definitions) that can be cited later.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from pydantic import BaseModel, Field

from webweaver.llm.client import ChatMessage, LLMClient
from webweaver.logging import get_logger
from webweaver.models.evidence import EvidenceItem
from webweaver.prompts import EVIDENCE_EXTRACTOR_SYSTEM_PROMPT
from webweaver.utils.tags import extract_json_object

logger = get_logger(__name__)


class EvidenceExtractionOutput(BaseModel):
    """Structured extraction output."""

    items: list[EvidenceItem] = Field(default_factory=list)


@dataclass(frozen=True)
class EvidenceExtractor:
    """Extract evidence items from a document."""

    llm: LLMClient

    def extract(self, *, query: str, text: str, max_items: int = 8) -> list[EvidenceItem]:
        """Extract evidence items.

        Args:
            query: Research query.
            text: Document text.
            max_items: Maximum number of evidence items.

        Returns:
            Evidence items.
        """

        messages = [
            ChatMessage(
                role="system",
                content=EVIDENCE_EXTRACTOR_SYSTEM_PROMPT,
            ),
            ChatMessage(
                role="user",
                content=(
                    f"Query: {query}\n\n"
                    "Document:\n"
                    f"{text}\n\n"
                    f"Extract up to {max_items} evidence items. "
                    "Return JSON: {\"items\": [ {\"type\": \"quote|data|definition|claim|case\", "
                    "\"content\": string, \"location\": string|null, \"confidence\": 0-1|null} ] }."
                ),
            ),
        ]

        raw = self.llm.complete(messages, temperature=0.1)
        data = extract_json_object(raw)
        if data is None:
            logger.warning("Failed to parse evidence extraction output; returning empty. Raw=%s", raw[:400])
            return []
        try:
            parsed = EvidenceExtractionOutput.model_validate(data)
            return parsed.items[:max_items]
        except Exception:
            logger.warning("Failed to validate evidence extraction JSON; returning empty. Raw=%s", raw[:400])
            return []

    async def extract_async(self, *, query: str, text: str, max_items: int = 8) -> list[EvidenceItem]:
        """Async variant of :meth:`extract`."""

        return await asyncio.to_thread(self.extract, query=query, text=text, max_items=max_items)
