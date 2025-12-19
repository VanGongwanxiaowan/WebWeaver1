#!/usr/bin/env python3
"""继续执行已有的运行，生成报告。

用法:
    python continue_report.py <run_id>

例如:
    python continue_report.py 20251219T103122Z_0b38a400
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from webweaver.config import Settings, load_settings
from webweaver.llm.client import LLMClient
from webweaver.logging import configure_logging, get_logger, set_step
from webweaver.memory.evidence_bank import EvidenceBank
from webweaver.models.outline import Outline
from webweaver.orchestrator.runner import (
    RunPaths,
    _clean_report_text,
    _format_tool_response,
    _prune_retrieved,
    _split_outline_sections,
)
from webweaver.agents.writer import WriterAgent, WriterAgentV2, WriterStepInputs
from webweaver.agents.writer_actions import RetrieveAction, WriteAction, WriterTerminateAction
from webweaver.utils.citations import extract_citation_ids
from webweaver.events import ContentType, EventType, RunEvent
from webweaver.recording.file_recorder import FileEventRecorder, iter_events

logger = get_logger(__name__)


def continue_report_from_outline(*, run_id: str, artifacts_dir: Path, query: str | None = None) -> Path:
    """从已有的outline和evidence继续生成报告。

    Args:
        run_id: 运行ID
        artifacts_dir: artifacts目录
        query: 查询字符串，如果为None则从events中读取

    Returns:
        生成的报告路径
    """
    run_dir = artifacts_dir / f"run_{run_id}"
    if not run_dir.exists():
        raise ValueError(f"Run directory not found: {run_dir}")

    paths = RunPaths(root=run_dir)

    # 读取query（如果未提供）
    if query is None:
        events_path = paths.events_path
        if events_path.exists():
            try:
                with open(events_path, "r", encoding="utf-8") as f:
                    for line in f:
                        event = json.loads(line)
                        if event.get("event_type") == "system" and event.get("content_type") == "message":
                            metadata = event.get("metadata", {})
                            query = metadata.get("query")
                            if query:
                                break
            except Exception as e:
                logger.warning(f"Failed to read query from events: {e}")

    if not query:
        query = "AIGC（AI生成内容）技术研究"  # 默认query

    logger.info(f"Continuing report generation for run {run_id}, query: {query}")

    settings = load_settings()
    llm = LLMClient(settings)
    evidence_bank = EvidenceBank(paths.evidence_root)

    # 读取outline
    if not paths.outline_path.exists():
        raise ValueError(f"Outline not found: {paths.outline_path}")
    outline_text = paths.outline_path.read_text(encoding="utf-8")
    outline = Outline(text=outline_text, version=1)

    # 记录events
    recorder = FileEventRecorder(paths.events_path)
    seq = len(list(iter_events(paths.events_path))) if paths.events_path.exists() else 0

    def emit(event_type: EventType, content_type: ContentType, data: str | dict | list | None = None, *, metadata: dict | None = None):
        nonlocal seq
        seq += 1
        from datetime import datetime
        ev = RunEvent(
            run_id=run_id,
            seq=seq,
            event_type=event_type,
            content_type=content_type,
            data=data,
            metadata=dict(metadata or {}),
        )
        recorder.append(ev)
        return ev

    # 开始writer阶段
    set_step("writer")
    writer = WriterAgentV2(llm=llm)
    logger.info("Writer started", extra={"evidence_count": evidence_bank.count()})
    emit(EventType.SYSTEM, ContentType.MESSAGE, "writer_started", metadata={"query": query})

    sections = _split_outline_sections(outline.text)
    report_parts: list[str] = []
    used_ids: set[str] = set()

    for sec_idx, (sec_title, sec_outline) in enumerate(sections, start=1):
        emit(
            EventType.SYSTEM,
            ContentType.WRITER_SECTION_START,
            data={"section_index": sec_idx, "title": sec_title},
        )
        set_step(f"writer:section:{sec_idx}")
        logger.info(f"Writing section {sec_idx}: {sec_title}")

        section_draft = ""
        tool_response: str | None = None
        section_citation_ids = extract_citation_ids(sec_outline)

        for step_in_section in range(settings.writer_max_steps_per_section):
            emit(
                EventType.SYSTEM,
                ContentType.WRITER_STEP,
                data={"section_index": sec_idx, "step": step_in_section + 1},
            )

            if len(section_draft) > settings.writer_section_max_chars:
                section_draft = section_draft[-settings.writer_section_max_chars :]

            try:
                action = writer.step(
                    WriterStepInputs(
                        query=query,
                        outline_text=f"## {sec_title}\n{sec_outline}",
                        draft=section_draft,
                        tool_response=tool_response,
                    )
                )
            except Exception as e:
                emit(
                    EventType.ERROR,
                    ContentType.MESSAGE,
                    data=str(e),
                    metadata={"stage": "writer", "section_index": sec_idx, "step": step_in_section + 1},
                )
                logger.exception(
                    "Writer step failed",
                    extra={"section_index": sec_idx, "step": step_in_section + 1},
                )
                break

            if isinstance(action, RetrieveAction):
                top_k = action.top_k or settings.writer_retrieve_top_k
                q = action.query or ""
                emit(
                    EventType.TOOL,
                    ContentType.WRITER_RETRIEVE_QUERY,
                    data={"section_index": sec_idx, "query": q},
                )
                try:
                    target_ids: list[str] | None = None
                    if action.citation_ids:
                        target_ids = action.citation_ids
                    elif section_citation_ids:
                        target_ids = section_citation_ids

                    retrieved_pairs: list[tuple[object, int]] = []
                    if target_ids:
                        evidences = evidence_bank.bulk_get(target_ids)
                        evidences = [
                            ev for ev in evidences if getattr(ev, "evidence_id", "") not in used_ids
                        ]
                        for ev in evidences[:top_k]:
                            retrieved_pairs.append((ev, 1))
                    else:
                        q = action.query or ""
                        retrieved_scored = evidence_bank.retrieve_scored(query=q, top_k=top_k)
                        retrieved_scored = [
                            (ev, score)
                            for ev, score in retrieved_scored
                            if getattr(ev, "evidence_id", "") not in used_ids
                        ]
                        retrieved_pairs = [(ev, score) for ev, score in retrieved_scored]

                    pruned, new_ids = _prune_retrieved(
                        retrieved_pairs,
                        max_evidences=settings.writer_section_max_evidences,
                        evidence_items_per_evidence=settings.writer_evidence_items_per_evidence,
                        max_chars=settings.writer_tool_response_max_chars,
                    )
                except Exception as e:
                    emit(
                        EventType.ERROR,
                        ContentType.MESSAGE,
                        data=str(e),
                        metadata={"tool": "retrieve", "section_index": sec_idx},
                    )
                    logger.exception(
                        "Retrieve failed",
                        extra={"section_index": sec_idx},
                    )
                    pruned, new_ids = [], set()
                used_ids |= new_ids

                if pruned:
                    tool_response = _format_tool_response(
                        pruned,
                        max_items=settings.writer_evidence_items_per_evidence,
                    )
                else:
                    tool_response = "<tool_response><material>NO_NEW_EVIDENCE</material></tool_response>"
                emit(
                    EventType.TOOL,
                    ContentType.WRITER_RETRIEVE_RESULTS,
                    data={
                        "section_index": sec_idx,
                        "count": len(pruned),
                        "evidence_ids": [getattr(e, "evidence_id", "") for e in pruned],
                    },
                )
                continue

            if isinstance(action, WriteAction):
                piece = action.text.strip()
                if piece:
                    section_draft = (section_draft + "\n\n" + piece).strip()
                emit(
                    EventType.LLM,
                    ContentType.WRITER_WRITE,
                    data={"section_index": sec_idx, "chars": len(piece)},
                )
                continue

            if isinstance(action, WriterTerminateAction):
                emit(
                    EventType.SYSTEM,
                    ContentType.WRITER_TERMINATE,
                    data={"section_index": sec_idx, "reason": action.reason},
                )
                break

        report_parts.append(f"## {sec_title}\n\n{section_draft.strip()}".strip())
        emit(
            EventType.SYSTEM,
            ContentType.WRITER_SECTION_DONE,
            data={"section_index": sec_idx, "title": sec_title, "chars": len(section_draft)},
        )
        logger.info(f"Section {sec_idx} completed: {len(section_draft)} chars")

    evidences_by_id = {e.evidence_id: e for e in evidence_bank.list_all()}
    refs = WriterAgent._render_references(sorted(used_ids), evidences_by_id)
    report = ("\n\n".join(report_parts).strip() + "\n\n" + refs).strip()
    report = _clean_report_text(report)
    paths.report_path.write_text(report, encoding="utf-8")
    logger.info("Report written", extra={"report_path": str(paths.report_path)})
    emit(
        EventType.SYSTEM,
        ContentType.REPORT_DONE,
        data={
            "report_path": str(paths.report_path),
            "outline_path": str(paths.outline_path),
            "events_path": str(paths.events_path),
            "run_root": str(paths.root),
        },
    )

    return paths.report_path


def main():
    if len(sys.argv) < 2:
        print("Usage: python continue_report.py <run_id>", file=sys.stderr)
        print("Example: python continue_report.py 20251219T103122Z_0b38a400", file=sys.stderr)
        sys.exit(1)

    run_id = sys.argv[1]
    settings = load_settings()
    configure_logging(settings.log_level)

    try:
        report_path = continue_report_from_outline(
            run_id=run_id,
            artifacts_dir=settings.artifacts_dir,
        )
        print(f"报告已生成: {report_path}")
    except Exception as e:
        logger.exception("Failed to continue report generation")
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

