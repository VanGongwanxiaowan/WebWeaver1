"""Writer agent.

The writer composes the report section-by-section by retrieving only cited evidence from the bank.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import re

from webweaver.llm.client import ChatMessage, LLMClient
from webweaver.models.evidence import Evidence
from webweaver.prompts import WRITER_SYSTEM_PROMPT
from webweaver.utils.citations import extract_citation_ids
from webweaver.utils.tags import parse_tool_call_payload
from webweaver.agents.writer_actions import (
    RetrieveAction,
    WriteAction,
    WriterTerminateAction,
)


@dataclass(frozen=True)
class WriterInputs:
    """Inputs for report writing."""

    query: str
    outline_text: str
    evidences_by_id: dict[str, Evidence]


class WriterAgent:
    """WebWeaver Writer agent."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def write(self, inputs: WriterInputs) -> str:
        """Write a full report (synchronous)."""

        sections = self._split_sections(inputs.outline_text)
        written_sections: list[str] = []
        used_ids: list[str] = []

        for title, body in sections:
            section_ids = extract_citation_ids(body)
            for eid in section_ids:
                if eid not in used_ids:
                    used_ids.append(eid)

            evidence_block = self._format_evidence(section_ids, inputs.evidences_by_id)
            section_text = self._write_section(
                query=inputs.query,
                title=title,
                outline_body=body,
                evidence=evidence_block,
            )
            written_sections.append(section_text)

        references = WriterAgent._render_references(used_ids, inputs.evidences_by_id)
        return "\n\n".join(written_sections) + "\n\n" + references

    async def write_async(self, inputs: WriterInputs) -> str:
        """Write a full report asynchronously with concurrent section writing.

        This offloads blocking LLM calls to worker threads and writes multiple
        sections in parallel, improving throughput in high-concurrency setups.
        """

        sections = self._split_sections(inputs.outline_text)
        used_ids: list[str] = []
        section_jobs: list[tuple[str, str]] = []  # (title, body)

        for title, body in sections:
            section_ids = extract_citation_ids(body)
            for eid in section_ids:
                if eid not in used_ids:
                    used_ids.append(eid)
            section_jobs.append((title, body))

        async def _write_one(title: str, body: str) -> str:
            section_ids = extract_citation_ids(body)
            evidence_block = self._format_evidence(section_ids, inputs.evidences_by_id)
            # Offload blocking _write_section to a thread
            return await asyncio.to_thread(
                self._write_section,
                query=inputs.query,
                title=title,
                outline_body=body,
                evidence=evidence_block,
            )

        tasks = [_write_one(title, body) for title, body in section_jobs]
        written_sections = await asyncio.gather(*tasks)

        references = WriterAgent._render_references(used_ids, inputs.evidences_by_id)
        return "\n\n".join(written_sections) + "\n\n" + references


_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(?P<json>\{.*?\})\s*</tool_call>", re.DOTALL)
_WRITE_RE = re.compile(r"<write>(?P<body>.*?)</write>", re.DOTALL)
_TERMINATE_RE = re.compile(r"<terminate>(?P<body>.*?)</terminate>", re.DOTALL)


@dataclass(frozen=True)
class WriterStepInputs:
    query: str
    outline_text: str
    draft: str
    tool_response: str | None = None


class WriterAgentV2:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def step(
        self, inputs: WriterStepInputs
    ) -> RetrieveAction | WriteAction | WriterTerminateAction:
        user = (
            f"User Query: {inputs.query}\n\n"
            "Outline:\n"
            f"{inputs.outline_text}\n\n"
            "Current Draft (may be partial):\n"
            f"{inputs.draft}\n\n"
        )
        if inputs.tool_response:
            user += "Latest <tool_response>:\n" + inputs.tool_response + "\n\n"
        user += "Decide next action."

        messages = [
            ChatMessage(role="system", content=WRITER_SYSTEM_PROMPT),
            ChatMessage(role="user", content=user),
        ]
        # Deterministic decoding to make tag parsing robust.
        raw = self._llm.complete(messages, temperature=0.0).strip()
        return self._parse_action(raw)

    async def step_async(
        self, inputs: WriterStepInputs
    ) -> RetrieveAction | WriteAction | WriterTerminateAction:
        """Async variant of :meth:`step` that runs the LLM call in a thread."""

        user = (
            f"User Query: {inputs.query}\n\n"
            "Outline:\n"
            f"{inputs.outline_text}\n\n"
            "Current Draft (may be partial):\n"
            f"{inputs.draft}\n\n"
        )
        if inputs.tool_response:
            user += "Latest <tool_response>:\n" + inputs.tool_response + "\n\n"
        user += "Decide next action."

        messages = [
            ChatMessage(role="system", content=WRITER_SYSTEM_PROMPT),
            ChatMessage(role="user", content=user),
        ]
        # Deterministic decoding to make tag parsing robust.
        raw = await asyncio.to_thread(self._llm.complete, messages, temperature=0.0)
        return self._parse_action(raw.strip())

    @staticmethod
    def _parse_action(raw: str) -> RetrieveAction | WriteAction | WriterTerminateAction:
        # 1) 优先解析 tool_call（检索动作）
        payload = parse_tool_call_payload(raw)
        if payload:
            name = payload.get("name")
            args = payload.get("arguments") or {}
            # 只处理 name == "retrieve" 的工具；其它 name 或缺失 name 时，
            # 视为非 tool_call，继续尝试解析 <write>/<terminate>。
            if name == "retrieve":
                return RetrieveAction.model_validate(args)

        # 2) 解析 <write>...</write>
        m = _WRITE_RE.search(raw)
        if m:
            body = m.group("body").strip()
            return WriteAction(text=body)

        # 3) 解析 <terminate>...</terminate>
        m = _TERMINATE_RE.search(raw)
        if m:
            return WriterTerminateAction(reason=m.group("body").strip())

        # Fallback: if the model forgot the tags but produced non-empty text,
        # treat it as a <write> action instead of failing the whole step.
        raw_stripped = raw.strip()
        if raw_stripped:
            return WriteAction(text=raw_stripped)

        raise ValueError("writer output did not contain a valid action tag")

    def _write_section(self, *, query: str, title: str, outline_body: str, evidence: str) -> str:
        messages = [
            ChatMessage(
                role="system",
                content=WRITER_SYSTEM_PROMPT,
            ),
            ChatMessage(
                role="user",
                content=(
                    f"User Query: {query}\n\n"
                    f"Section Title: {title}\n\n"
                    "Outline Notes (may contain citation tags):\n"
                    f"{outline_body}\n\n"
                    "Evidence (citeable):\n"
                    f"{evidence}\n\n"
                    "Write this section in markdown, with factual claims supported by footnotes."
                ),
            ),
        ]
        return self._llm.complete(messages, temperature=0.2).strip()

    @staticmethod
    def _split_sections(outline_text: str) -> list[tuple[str, str]]:
        lines = outline_text.splitlines()
        sections: list[tuple[str, str]] = []
        current_title = "Report"
        buf: list[str] = []

        def flush() -> None:
            nonlocal buf
            if buf:
                sections.append((current_title, "\n".join(buf).strip()))
                buf = []

        for line in lines:
            if line.startswith("## "):
                flush()
                current_title = line.removeprefix("## ").strip() or "Section"
                buf.append(line)
            else:
                buf.append(line)
        flush()

        if not sections:
            return [("Report", outline_text)]
        return sections

    @staticmethod
    def _format_evidence(evidence_ids: list[str], evidences_by_id: dict[str, Evidence]) -> str:
        if not evidence_ids:
            return "<no evidence cited>"

        blocks: list[str] = []
        for eid in evidence_ids:
            ev = evidences_by_id.get(eid)
            if ev is None:
                continue
            blocks.append(f"[{eid}] {ev.source.title or ''} | {ev.source.url}")
            blocks.append(f"Summary: {ev.summary}")
            if ev.evidence_items:
                for item in ev.evidence_items[:8]:
                    loc = f" ({item.location})" if item.location else ""
                    blocks.append(f"- {item.type}{loc}: {item.content}")
            blocks.append("")
        return "\n".join(blocks).strip()

    @staticmethod
    def _render_references(used_ids: list[str], evidences_by_id: dict[str, Evidence]) -> str:
        lines = ["# References"]
        for eid in used_ids:
            ev = evidences_by_id.get(eid)
            if ev is None:
                continue
            title = ev.source.title or "Untitled"
            lines.append(f"[^{eid}]: {title}. {ev.source.url}")
        return "\n".join(lines)


# 将_render_references也添加到WriterAgent类中，以便兼容性
WriterAgent._render_references = WriterAgentV2._render_references
