"""Summarization middleware for WebWeaver agents.

Automatically summarizes conversation history when context exceeds token limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from webweaver.llm.client import ChatMessage, LLMClient
from webweaver.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SummarizationConfig:
    """Configuration for summarization middleware."""

    trigger_tokens: int = 170000  # Trigger summarization at this token count
    keep_messages: int = 6  # Keep this many recent messages after summarization
    trigger_fraction: float | None = None  # Alternative: trigger at fraction of max tokens
    keep_fraction: float | None = None  # Alternative: keep fraction of messages


class SummarizationMiddleware:
    """Middleware that automatically summarizes conversation history.

    When the conversation context exceeds a token threshold, this middleware
    summarizes older messages and keeps only recent ones to manage context size.
    """

    def __init__(
        self,
        llm: LLMClient,
        config: SummarizationConfig | None = None,
    ) -> None:
        """Initialize summarization middleware.

        Args:
            llm: LLM client for generating summaries.
            config: Summarization configuration.
        """
        self._llm = llm
        self._config = config or SummarizationConfig()

    def should_summarize(self, messages: list[dict[str, Any]], estimated_tokens: int) -> bool:
        """Check if summarization should be triggered.

        Args:
            messages: List of messages.
            estimated_tokens: Estimated token count.

        Returns:
            True if summarization should be triggered.
        """
        if self._config.trigger_fraction:
            # Fraction-based triggering would need max_tokens from model
            # For now, use token-based
            pass

        return estimated_tokens >= self._config.trigger_tokens

    def summarize_messages(
        self,
        messages: list[dict[str, Any]],
        user_query: str | None = None,
    ) -> str:
        """Summarize a list of messages.

        Args:
            messages: Messages to summarize.
            user_query: Optional user query for context.

        Returns:
            Summary text.
        """
        # Build summary prompt
        prompt_parts = [
            "Summarize the following conversation history, focusing on:",
            "- Key decisions and actions taken",
            "- Important information and context",
            "- Current state and progress",
            "",
            "Conversation:",
        ]

        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                prompt_parts.append(f"{role}: {content[:500]}")  # Truncate for summary

        if user_query:
            prompt_parts.append(f"\nCurrent user query: {user_query}")

        prompt = "\n".join(prompt_parts)

        summary_messages = [
            ChatMessage(
                role="system",
                content="You are a helpful assistant that summarizes conversations concisely.",
            ),
            ChatMessage(role="user", content=prompt),
        ]

        try:
            summary = self._llm.complete(summary_messages, temperature=0.1)
            logger.info("Messages summarized", extra={"original_count": len(messages)})
            return summary
        except Exception as e:
            logger.exception("Failed to summarize messages")
            return f"[Summary generation failed: {e}]"

    def process_messages(
        self,
        messages: list[dict[str, Any]],
        estimated_tokens: int,
        user_query: str | None = None,
    ) -> list[dict[str, Any]]:
        """Process messages and summarize if needed.

        Args:
            messages: List of messages.
            estimated_tokens: Estimated token count.
            user_query: Optional current user query.

        Returns:
            Processed message list (possibly with summary).
        """
        if not self.should_summarize(messages, estimated_tokens):
            return messages

        # Determine how many messages to keep
        keep_count = self._config.keep_messages
        if self._config.keep_fraction:
            keep_count = max(1, int(len(messages) * self._config.keep_fraction))

        # Split messages
        to_summarize = messages[:-keep_count] if len(messages) > keep_count else []
        to_keep = messages[-keep_count:] if len(messages) > keep_count else messages

        if not to_summarize:
            return messages

        # Generate summary
        summary_text = self.summarize_messages(to_summarize, user_query)

        # Build new message list with summary
        summary_msg = {
            "type": "system",
            "role": "system",
            "content": f"[Previous conversation summarized]: {summary_text}",
        }

        return [summary_msg] + to_keep

