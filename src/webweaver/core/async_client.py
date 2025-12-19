"""Async LLM client with connection pooling and rate limiting."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from webweaver.config import Settings
from webweaver.logging import get_logger
from webweaver.llm.client import ChatMessage

logger = get_logger(__name__)


@dataclass
class RateLimiter:
    """Token bucket rate limiter."""

    max_tokens: int
    refill_rate: float  # tokens per second
    bucket: float = 0.0
    last_refill: float = 0.0
    _lock: asyncio.Lock = None

    def __post_init__(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        self.last_refill = time.monotonic()
        self.bucket = float(self.max_tokens)

    async def acquire(self, tokens: int) -> None:
        """Acquire tokens, waiting if necessary."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.bucket = min(self.max_tokens, self.bucket + elapsed * self.refill_rate)
            self.last_refill = now

            while self.bucket < tokens:
                wait_time = (tokens - self.bucket) / self.refill_rate
                await asyncio.sleep(wait_time)
                now = time.monotonic()
                elapsed = now - self.last_refill
                self.bucket = min(self.max_tokens, self.bucket + elapsed * self.refill_rate)
                self.last_refill = now

            self.bucket -= tokens


class AsyncLLMClient:
    """Async LLM client with connection pooling, rate limiting, and retry logic."""

    def __init__(
        self,
        settings: Settings,
        *,
        max_concurrent: int = 10,
        rate_limit_tpm: int = 1000000,  # tokens per minute
        max_retries: int = 3,
        retry_backoff: float = 1.0,
    ) -> None:
        """Initialize async LLM client.

        Args:
            settings: Application settings.
            max_concurrent: Maximum concurrent requests.
            rate_limit_tpm: Rate limit in tokens per minute.
            max_retries: Maximum retry attempts.
            retry_backoff: Backoff multiplier for retries.
        """
        self._settings = settings
        if not settings.openai_api_key:
            raise ValueError(
                "Missing WEBWEAVER_OPENAI_API_KEY. "
                "Set it in environment variables or a .env file."
            )

        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            max_retries=0,  # We handle retries ourselves
        )

        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._rate_limiter = RateLimiter(
            max_tokens=rate_limit_tpm,
            refill_rate=rate_limit_tpm / 60.0,  # tokens per second
        )
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff

        # Metrics
        self._request_count = 0
        self._error_count = 0
        self._total_tokens = 0
        self._total_latency = 0.0

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a completion asynchronously.

        Args:
            messages: Chat messages.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.

        Returns:
            Assistant message content.
        """
        async with self._semaphore:
            return await self._complete_with_retry(messages, temperature=temperature, max_tokens=max_tokens)

    async def _complete_with_retry(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        """Complete with retry logic."""
        payload: list[dict[str, str]] = [{"role": m.role, "content": m.content} for m in messages]

        # Estimate tokens (rough: 4 chars per token)
        estimated_tokens = sum(len(m.content) for m in messages) // 4 + (max_tokens or 2000)
        await self._rate_limiter.acquire(estimated_tokens)

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                start_time = time.monotonic()
                resp: ChatCompletion = await self._client.chat.completions.create(
                    model=self._settings.openai_model,
                    messages=payload,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=self._settings.openai_timeout_s,
                )
                latency = time.monotonic() - start_time

                self._request_count += 1
                self._total_latency += latency

                choice = resp.choices[0]
                if not choice.message or choice.message.content is None:
                    return ""

                # Track actual tokens used
                if resp.usage:
                    self._total_tokens += resp.usage.total_tokens

                logger.debug(
                    "LLM completion successful",
                    extra={
                        "model": self._settings.openai_model,
                        "latency_ms": latency * 1000,
                        "tokens": resp.usage.total_tokens if resp.usage else None,
                    },
                )

                return choice.message.content

            except Exception as e:
                last_error = e
                self._error_count += 1

                if attempt < self._max_retries:
                    wait_time = self._retry_backoff * (2 ** attempt)
                    logger.warning(
                        "LLM request failed, retrying",
                        extra={
                            "attempt": attempt + 1,
                            "max_retries": self._max_retries,
                            "wait_time": wait_time,
                            "error": str(e),
                        },
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error("LLM request failed after retries", extra={"error": str(e)})

        raise RuntimeError(f"LLM request failed after {self._max_retries} retries: {last_error}") from last_error

    async def complete_batch(
        self,
        requests: list[tuple[list[ChatMessage], dict[str, Any]]],
    ) -> list[str]:
        """Complete multiple requests concurrently.

        Args:
            requests: List of (messages, kwargs) tuples.

        Returns:
            List of completion results.
        """
        tasks = [
            self.complete(messages, **kwargs) for messages, kwargs in requests
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)

    def get_metrics(self) -> dict[str, Any]:
        """Get client metrics."""
        avg_latency = (
            self._total_latency / self._request_count if self._request_count > 0 else 0.0
        )
        error_rate = (
            self._error_count / self._request_count if self._request_count > 0 else 0.0
        )

        return {
            "request_count": self._request_count,
            "error_count": self._error_count,
            "error_rate": error_rate,
            "total_tokens": self._total_tokens,
            "avg_latency_ms": avg_latency * 1000,
            "total_latency_ms": self._total_latency * 1000,
        }

    def reset_metrics(self) -> None:
        """Reset metrics."""
        self._request_count = 0
        self._error_count = 0
        self._total_tokens = 0
        self._total_latency = 0.0

