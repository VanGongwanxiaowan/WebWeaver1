"""Web search tool abstraction."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import httpx
from duckduckgo_search import DDGS

from webweaver.config import Settings
from webweaver.logging import get_logger
from webweaver.models.search import SearchResult

logger = get_logger(__name__)


class WebSearchProvider(Protocol):
    """Search provider interface."""

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        """Search web."""


class WebSearchError(RuntimeError):
    pass


class TavilySearchError(WebSearchError):
    pass


@dataclass(frozen=True)
class TavilySearchProvider:
    """Tavily API search provider.

    Notes:
        - API key must be provided via settings (`WEBWEAVER_TAVILY_API_KEY`).
        - This provider intentionally returns only URL/title/snippet and keeps raw content fetching
          in the page fetcher/parser pipeline.
    """

    api_key: str
    base_url: str = "https://api.tavily.com"
    search_depth: str = "basic"
    timeout_s: float = 30.0
    max_retries: int = 3
    retry_backoff_s: float = 0.75
    retry_max_backoff_s: float = 8.0
    source_name: str = "tavily"

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        """Search using Tavily.

        Args:
            query: Search query.
            max_results: Maximum number of results.

        Returns:
            List of results.
        """

        url = f"{self.base_url.rstrip('/')}/search"
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": self.search_depth,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }

        last_err: Exception | None = None
        started = time.monotonic()

        with httpx.Client(
            timeout=httpx.Timeout(self.timeout_s),
            follow_redirects=True,
        ) as client:
            for attempt in range(self.max_retries + 1):
                attempt_started = time.monotonic()
                request_id: str | None = None
                status_code: int | None = None

                try:
                    resp = client.post(url, json=payload)
                    status_code = resp.status_code
                    request_id = resp.headers.get("x-request-id") or resp.headers.get("x-amzn-trace-id")

                    if status_code in {429, 500, 502, 503, 504}:
                        raise httpx.HTTPStatusError(
                            f"tavily transient status={status_code}",
                            request=resp.request,
                            response=resp,
                        )

                    resp.raise_for_status()
                    data = resp.json()
                    if not isinstance(data, dict):
                        raise TavilySearchError("tavily response not a JSON object")

                    raw_results = data.get("results")
                    if not isinstance(raw_results, list):
                        raise TavilySearchError("tavily response missing results list")

                    results: list[SearchResult] = []
                    for i, item in enumerate(raw_results, start=1):
                        if not isinstance(item, dict):
                            continue
                        item_url = item.get("url")
                        if not item_url:
                            continue
                        try:
                            results.append(
                                SearchResult(
                                    title=item.get("title"),
                                    snippet=item.get("content") or item.get("snippet"),
                                    url=item_url,
                                    source=self.source_name,
                                    rank=i,
                                )
                            )
                        except Exception:
                            continue

                    logger.info(
                        "Tavily search ok",
                        extra={
                            "provider": self.source_name,
                            "query_len": len(query),
                            "max_results": max_results,
                            "search_depth": self.search_depth,
                            "attempt": attempt,
                            "status_code": status_code,
                            "result_count": len(results),
                            "request_id": request_id,
                            "latency_ms": int((time.monotonic() - attempt_started) * 1000),
                        },
                    )

                    return results
                except (httpx.TimeoutException, httpx.RequestError) as e:
                    last_err = e
                except httpx.HTTPStatusError as e:
                    last_err = e
                except Exception as e:
                    last_err = e

                should_retry = attempt < self.max_retries
                if not should_retry:
                    break

                retry_after_s: float | None = None
                if isinstance(last_err, httpx.HTTPStatusError) and last_err.response is not None:
                    try:
                        if last_err.response.status_code == 429:
                            ra = last_err.response.headers.get("retry-after")
                            if ra is not None:
                                retry_after_s = float(ra)
                    except Exception:
                        retry_after_s = None

                backoff = min(self.retry_max_backoff_s, self.retry_backoff_s * (2**attempt))
                sleep_s = retry_after_s if retry_after_s is not None else backoff
                logger.warning(
                    "Tavily search retry",
                    extra={
                        "provider": self.source_name,
                        "query_len": len(query),
                        "attempt": attempt,
                        "max_retries": self.max_retries,
                        "status_code": status_code,
                        "request_id": request_id,
                        "sleep_s": sleep_s,
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    },
                )
                time.sleep(sleep_s)

        msg = "Tavily search failed"
        logger.error(
            msg,
            extra={
                "provider": self.source_name,
                "query_len": len(query),
                "max_results": max_results,
                "search_depth": self.search_depth,
                "max_retries": self.max_retries,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "error_type": type(last_err).__name__ if last_err is not None else None,
                "error": str(last_err) if last_err is not None else None,
            },
        )
        raise TavilySearchError(msg) from last_err


@dataclass(frozen=True)
class DuckDuckGoSearchProvider:
    """DuckDuckGo search provider."""

    source_name: str = "duckduckgo"

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        """Search using DuckDuckGo.

        Args:
            query: Search query.
            max_results: Maximum number of results.

        Returns:
            List of results.
        """

        results: list[SearchResult] = []
        try:
            with DDGS() as ddgs:
                for i, r in enumerate(ddgs.text(query, max_results=max_results), start=1):
                    url = r.get("href") or r.get("url")
                    if not url:
                        continue
                    try:
                        results.append(
                            SearchResult(
                                title=r.get("title"),
                                snippet=r.get("body") or r.get("snippet"),
                                url=url,
                                source=self.source_name,
                                rank=i,
                            )
                        )
                    except Exception:
                        # Skip invalid URLs that cannot be parsed by Pydantic's HttpUrl
                        continue
        except Exception as e:
            logger.exception("Search failed for query=%s: %s", query, e)
            return []

        return results


def get_search_provider(settings: Settings) -> WebSearchProvider:
    """Factory to create a search provider based on settings."""

    if settings.search_provider == "tavily":
        if not settings.tavily_api_key:
            raise ValueError(
                "Missing WEBWEAVER_TAVILY_API_KEY while search_provider=tavily. "
                "Set it in environment variables or .env."
            )
        return TavilySearchProvider(
            api_key=settings.tavily_api_key,
            base_url=settings.tavily_api_base_url,
            search_depth=settings.tavily_search_depth,
            timeout_s=settings.tavily_timeout_s,
            max_retries=settings.tavily_max_retries,
            retry_backoff_s=settings.tavily_retry_backoff_s,
            retry_max_backoff_s=settings.tavily_retry_max_backoff_s,
        )

    return DuckDuckGoSearchProvider()
