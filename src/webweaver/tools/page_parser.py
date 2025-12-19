"""Page parsing utilities."""

from __future__ import annotations

from bs4 import BeautifulSoup
from readability import Document

from webweaver.logging import get_logger
from webweaver.models.document import ParsedDocument

logger = get_logger(__name__)


class PageParser:
    """Parse fetched HTML pages into cleaned text."""

    def parse_html(self, url: str, html: str, *, content_type: str | None = None) -> ParsedDocument:
        """Parse HTML into a readable document."""

        try:
            doc = Document(html)
            title = doc.short_title() or None
            content_html = doc.summary(html_partial=True)
            soup = BeautifulSoup(content_html, "lxml")
            text = soup.get_text("\n", strip=True)
        except Exception as e:
            logger.exception("Failed to parse html for url=%s: %s", url, e)
            soup = BeautifulSoup(html, "lxml")
            title = soup.title.get_text(strip=True) if soup.title else None
            text = soup.get_text("\n", strip=True)

        text = self._normalize_text(text)
        text = self._truncate(text, max_chars=25_000)

        return ParsedDocument(url=url, title=title, text=text, content_type=content_type)

    @staticmethod
    def _normalize_text(text: str) -> str:
        return "\n".join([line.strip() for line in text.splitlines() if line.strip()])

    @staticmethod
    def _truncate(text: str, *, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n\n[TRUNCATED]"
