"""LLM-based URL filtering.

This tool reduces noise by selecting relevant URLs using only titles/snippets from search results.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from pydantic import BaseModel, Field

from webweaver.llm.client import ChatMessage, LLMClient
from webweaver.logging import get_logger
from webweaver.models.search import SearchResult
from webweaver.prompts import URL_FILTER_SYSTEM_PROMPT
from webweaver.utils.tags import extract_json_object

logger = get_logger(__name__)


class UrlFilterDecision(BaseModel):
    """Decision output from the URL filter."""

    selected_ranks: list[int] = Field(default_factory=list)
    rationale: str = Field(default="")


@dataclass(frozen=True)
class UrlFilter:
    """Filter search results to select relevant URLs."""

    llm: LLMClient

    def select_urls(
        self,
        query: str,
        results: list[SearchResult],
        *,
        max_urls: int,
    ) -> list[SearchResult]:
        """Select relevant URLs.

        Args:
            query: User/planner query.
            results: Search results.
            max_urls: Maximum urls to keep.

        Returns:
            Filtered results.
        """

        if not results:
            return []
        if len(results) <= max_urls:
            return results

        prompt = self._build_prompt(query, results, max_urls=max_urls)
        messages = [
            ChatMessage(
                role="system",
                content=URL_FILTER_SYSTEM_PROMPT,
            ),
            ChatMessage(role="user", content=prompt),
        ]

        raw = self.llm.complete(messages, temperature=0.0)
        decision = self._parse_decision(raw)
        if not decision.selected_ranks:
            return results[:max_urls]

        selected: list[SearchResult] = []
        rank_to_result = {r.rank: r for r in results}
        for rnk in decision.selected_ranks:
            r = rank_to_result.get(rnk)
            if r is not None:
                selected.append(r)
        if not selected:
            return results[:max_urls]
        return selected[:max_urls]

    @staticmethod
    def _build_prompt(query: str, results: list[SearchResult], *, max_urls: int) -> str:
        lines = [
            f"Query: {query}",
            "",
            "Search results:",
        ]
        for r in results:
            title = r.title or ""
            snippet = r.snippet or ""
            lines.append(f"[{r.rank}] {title}")
            if snippet:
                lines.append(f"Snippet: {snippet}")
            lines.append(f"URL: {r.url}")
            lines.append("")

        lines.extend(
            [
                f"Select up to {max_urls} results.",
                "Return STRICT JSON with keys: selected_ranks (list of integers), rationale (string).",
                "Do not output anything else.",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _parse_decision(raw: str) -> UrlFilterDecision:
        data = extract_json_object(raw)
        if data is None:
            logger.warning("Failed to parse url filter output; fallback. Raw=%s", raw[:300])
            return UrlFilterDecision(selected_ranks=[], rationale="parse_failed")
        try:
            return UrlFilterDecision.model_validate(data)
        except Exception:
            logger.warning("Failed to validate url filter JSON; fallback. Raw=%s", raw[:300])
            return UrlFilterDecision(selected_ranks=[], rationale="validate_failed")

    async def select_urls_async(
        self,
        query: str,
        results: list[SearchResult],
        *,
        max_urls: int,
    ) -> list[SearchResult]:
        """Async variant of :meth:`select_urls`."""

        return await asyncio.to_thread(self.select_urls, query, results, max_urls=max_urls)
