from __future__ import annotations

from webweaver.prompts.planner import PLANNER_SYSTEM_PROMPT
from webweaver.prompts.tools import EVIDENCE_EXTRACTOR_SYSTEM_PROMPT, SUMMARIZER_SYSTEM_PROMPT, URL_FILTER_SYSTEM_PROMPT
from webweaver.prompts.writer import WRITER_SYSTEM_PROMPT

__all__ = [
    "PLANNER_SYSTEM_PROMPT",
    "WRITER_SYSTEM_PROMPT",
    "URL_FILTER_SYSTEM_PROMPT",
    "SUMMARIZER_SYSTEM_PROMPT",
    "EVIDENCE_EXTRACTOR_SYSTEM_PROMPT",
]
