"""Page fetching utilities."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from webweaver.config import Settings
from webweaver.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class FetchedPage:
    """Fetched page payload."""

    url: str
    content: bytes
    content_type: str | None


class PageFetcher:
    """Fetch pages over HTTP."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.Client(
            timeout=httpx.Timeout(settings.http_timeout_s),
            headers={"User-Agent": settings.http_user_agent},
            follow_redirects=True,
        )

    def fetch(self, url: str) -> FetchedPage:
        """Fetch a URL (synchronous)."""

        resp = self._client.get(url)
        resp.raise_for_status()
        return FetchedPage(
            url=str(resp.url),
            content=resp.content,
            content_type=resp.headers.get("content-type"),
        )

    async def fetch_async(self, url: str) -> FetchedPage:
        """Async variant of :meth:`fetch`."""

        return await asyncio.to_thread(self.fetch, url)
