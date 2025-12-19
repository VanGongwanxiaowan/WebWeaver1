"""End-to-end workflow runner."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Iterator

from webweaver.agents.actions import SearchAction, TerminateAction, WriteOutlineAction
from webweaver.agents.planner import PlannerAgent, PlannerInputs
from webweaver.agents.writer import (
    WriterAgent,
    WriterInputs,
    WriterAgentV2,
    WriterStepInputs,
)
from webweaver.agents.writer_actions import RetrieveAction, WriteAction, WriterTerminateAction
from webweaver.config import Settings
from webweaver.events import ContentType, EventType, RunEvent
from webweaver.evaluation.outline_judge import OutlineJudge
from webweaver.llm.client import ChatMessage, LLMClient
from webweaver.logging import get_logger, run_context, set_step
from webweaver.memory.evidence_bank import EvidenceBank
from webweaver.models.evidence import EvidenceSource
from webweaver.models.outline import Outline
from webweaver.recording.file_recorder import FileEventRecorder, iter_events
from webweaver.recording.redis_recorder import RedisEventRecorder
from webweaver.tools.evidence_extractor import EvidenceExtractor
from webweaver.tools.page_fetcher import PageFetcher
from webweaver.tools.page_parser import PageParser
from webweaver.tools.summarizer import Summarizer
from webweaver.tools.url_filter import UrlFilter
from webweaver.tools.web_search import WebSearchError, get_search_provider
from webweaver.utils.citations import extract_citation_ids

logger = get_logger(__name__)


def _repo_root() -> Path:
    # /.../src/webweaver/orchestrator/runner.py -> parents[3] == repo root
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class RunPaths:
    """Paths for a run."""

    root: Path

    @property
    def evidence_root(self) -> Path:
        return self.root / "evidence_bank"

    @property
    def outline_path(self) -> Path:
        return self.root / "outline.md"

    @property
    def report_path(self) -> Path:
        return self.root / "report.md"

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"


def run_research(*, query: str, settings: Settings) -> Path:
    """Run the workflow and return the report path.

    This is a convenience wrapper around :func:`run_research_stream`.
    """

    report_path: Path | None = None
    for ev in run_research_stream(query=query, settings=settings):
        if ev.content_type == ContentType.REPORT_DONE and isinstance(ev.data, dict):
            p = ev.data.get("report_path")
            if isinstance(p, str):
                report_path = Path(p)
    if report_path is None:
        raise RuntimeError("run completed without producing a report")
    return report_path


async def run_research_stream_async(*, query: str, settings: Settings) -> AsyncIterator[RunEvent]:
    """Async version of the full workflow, yielding events for streaming.

    与 ``run_research_stream`` 共享相同的业务流程，但将所有重度 I/O
    和 LLM 调用通过 ``asyncio`` 异步化，适合在高并发的 async 服务器中使用。

    注意：
        - 不修改原有 ``run_research_stream``，保持同步 fallback 路径稳定。
        - 本函数是一个 async generator，可 ``async for`` 流式消费事件。
    """

    run_id, run_root = _prepare_run_dir(settings.artifacts_dir)
    paths = RunPaths(root=run_root)
    recorder = FileEventRecorder(paths.events_path)

    redis_recorder: RedisEventRecorder | None = None
    if settings.redis_enabled:
        redis_recorder = RedisEventRecorder(
            redis_url=settings.redis_url,
            key_prefix=settings.redis_key_prefix,
            run_id=run_id,
        )
        redis_recorder.set_meta({"run_root": str(paths.root)})

    seq = 0

    def emit(
        event_type: EventType,
        content_type: ContentType,
        data: str | dict | list | None = None,
        *,
        metadata: dict[str, str | int | float | bool | None] | None = None,
    ) -> RunEvent:
        nonlocal seq
        seq += 1
        ev = RunEvent(
            run_id=run_id,
            seq=seq,
            event_type=event_type,
            content_type=content_type,
            data=data,
            metadata=dict(metadata or {}),
        )
        recorder.append(ev)
        if redis_recorder is not None:
            redis_recorder.append(ev)
        return ev

    with run_context(run_id=run_id, step="init"):
        logger.info("Run started (async)", extra={"query": query, "artifacts": str(paths.root)})
        yield emit(EventType.SYSTEM, ContentType.MESSAGE, "run_started", metadata={"query": query})

        # 仍然复用现有同步 LLMClient，但在下游通过 asyncio.to_thread/offload 的方式避免阻塞事件循环
        llm = LLMClient(settings)
        evidence_bank = EvidenceBank(paths.evidence_root)

        search_provider = get_search_provider(settings)
        url_filter = UrlFilter(llm=llm)
        fetcher = PageFetcher(settings)
        parser = PageParser()
        summarizer = Summarizer(llm=llm)
        extractor = EvidenceExtractor(llm=llm)
        planner = PlannerAgent(llm=llm)

        outline: Outline | None = None

        # -------- Planner loop (async, LLM 调用异步 offload) --------
        for step_idx in range(settings.planner_max_steps):
            set_step(f"planner:{step_idx + 1}")
            logger.info(
                "Planner step start (async)",
                extra={"step_index": step_idx + 1, "max_steps": settings.planner_max_steps},
            )
            yield emit(
                EventType.SYSTEM,
                ContentType.PLANNER_STEP,
                data={"step": step_idx + 1, "max_steps": settings.planner_max_steps},
            )

            evidences = evidence_bank.list_all()
            action = await planner.step_async(
                PlannerInputs(
                    query=query,
                    outline=outline,
                    evidences=evidences,
                    step_index=step_idx,
                    max_steps=settings.planner_max_steps,
                )
            )

            if isinstance(action, TerminateAction):
                # 如果在尚未产生任何大纲时就请求终止，视为异常情况，转为一次保守的搜索动作，
                # 避免直接回退到空大纲。
                if outline is None:
                    logger.warning(
                        "Planner requested early terminate without outline; "
                        "falling back to SearchAction for initial evidence.",
                        extra={"reason": action.reason},
                    )
                    action = SearchAction(
                        queries=[query],
                        goal="Collect initial evidence in Chinese for the research outline.",
                    )
                else:
                    logger.info("Planner terminated", extra={"reason": action.reason})
                    yield emit(EventType.SYSTEM, ContentType.PLANNER_TERMINATE, data=action.reason)
                    break

            if isinstance(action, WriteOutlineAction):
                outline = Outline(
                    text=action.outline_text,
                    version=(outline.version + 1 if outline else 1),
                )
                paths.outline_path.write_text(outline.text, encoding="utf-8")
                logger.info(
                    "Outline updated",
                    extra={"version": outline.version, "outline_path": str(paths.outline_path)},
                )
                yield emit(
                    EventType.LLM,
                    ContentType.OUTLINE_UPDATED,
                    data={"version": outline.version, "outline_path": str(paths.outline_path)},
                )
                continue

            if isinstance(action, SearchAction):
                logger.info(
                    "Planner search action (async)",
                    extra={"queries": action.queries[: settings.planner_max_queries_per_step]},
                )
                
                # 按查询顺序处理，但每个查询内的URL并发处理
                for q in action.queries[: settings.planner_max_queries_per_step]:
                    yield emit(EventType.TOOL, ContentType.SEARCH_QUERY, data=q)
                    
                    # 1. 搜索（使用异步 offload）
                    try:
                        results = await asyncio.to_thread(
                            search_provider.search,
                            q,
                            max_results=settings.search_max_results,
                        )
                    except WebSearchError as e:
                        yield emit(
                            EventType.ERROR,
                            ContentType.MESSAGE,
                            data=str(e),
                            metadata={
                                "tool": "web_search",
                                "provider": settings.search_provider,
                                "query": q,
                            },
                        )
                        logger.exception(
                            "Search provider failed (async)",
                            extra={"provider": settings.search_provider, "query": q},
                        )
                        results = []
                    except Exception as e:
                        yield emit(
                            EventType.ERROR,
                            ContentType.MESSAGE,
                            data=str(e),
                            metadata={
                                "tool": "web_search",
                                "provider": settings.search_provider,
                                "query": q,
                            },
                        )
                        logger.exception(
                            "Unexpected search error (async)",
                            extra={"provider": settings.search_provider, "query": q},
                        )
                        results = []
                    
                    logger.info(
                        "Search results (async)",
                        extra={"query": q, "results": len(results), "provider": settings.search_provider},
                    )
                    yield emit(
                        EventType.TOOL,
                        ContentType.SEARCH_RESULTS,
                        data=[r.model_dump(mode="json") for r in results],
                    )
                    
                    if not results:
                        continue
                    
                    # 2. URL过滤（使用新的异步方法）
                    try:
                        selected = await url_filter.select_urls_async(
                            q,
                            results,
                            max_urls=settings.planner_max_urls_per_query,
                        )
                    except Exception as e:
                        yield emit(
                            EventType.ERROR,
                            ContentType.MESSAGE,
                            data=str(e),
                            metadata={"tool": "url_filter", "query": q},
                        )
                        logger.exception("URL filter failed (async); fallback to top results", extra={"query": q})
                        selected = results[: settings.planner_max_urls_per_query]
                    
                    logger.info(
                        "URLs selected (async)",
                        extra={"query": q, "selected": len(selected)},
                    )
                    
                    if not selected:
                        continue
                    
                    # 3. 并发处理多个URL（使用 asyncio.gather，保持事件顺序）
                    async def process_single_url(r: object) -> tuple[str, dict | None, Exception | None]:
                        """处理单个URL：抓取 -> 解析 -> 摘要 -> 提取证据
                        
                        返回: (url_str, evidence_data_or_none, error_or_none)
                        """
                        url_str = str(r.url)
                        error: Exception | None = None
                        evidence_data: dict | None = None
                        
                        try:
                            # 使用新的异步方法
                            fetched = await fetcher.fetch_async(url_str)
                            html = fetched.content.decode("utf-8", errors="ignore")
                            doc = await asyncio.to_thread(
                                parser.parse_html,
                                url_str,
                                html,
                                content_type=fetched.content_type,
                            )
                            
                            # 使用新的异步方法
                            summary = await summarizer.summarize_async(query=query, text=doc.text)
                            if summary.strip().upper().startswith("NOT RELEVANT"):
                                logger.info("Page not relevant (async)", extra={"url": url_str})
                                return (url_str, None, None)
                            
                            # 使用新的异步方法
                            items = await extractor.extract_async(query=query, text=doc.text, max_items=8)
                            
                            source = EvidenceSource(url=url_str, title=doc.title)
                            ev = await asyncio.to_thread(
                                evidence_bank.add,
                                query=q,
                                source=source,
                                summary=summary,
                                evidence_items=items,
                                raw_text=doc.text,
                                tags=[],
                            )
                            
                            logger.info(
                                "Evidence added (async)",
                                extra={"evidence_id": ev.evidence_id, "url": str(ev.source.url)},
                            )
                            
                            evidence_data = {
                                "evidence_id": ev.evidence_id,
                                "url": str(ev.source.url),
                            }
                        except Exception as e:
                            error = e
                            logger.exception(
                                "Failed processing url (async)",
                                extra={"url": url_str},
                            )
                        
                        return (url_str, evidence_data, error)
                    
                    # 并发处理所有选中的URL
                    url_results = await asyncio.gather(*[process_single_url(r) for r in selected])
                    
                    # 按顺序 yield 事件（保持事件顺序）
                    for url_str, evidence_data, error in url_results:
                        yield emit(EventType.TOOL, ContentType.URL_SELECTED, data=url_str)
                        
                        if error is not None:
                            yield emit(
                                EventType.ERROR,
                                ContentType.MESSAGE,
                                data=str(error),
                                metadata={"url": url_str},
                            )
                        elif evidence_data is not None:
                            yield emit(
                                EventType.TOOL,
                                ContentType.EVIDENCE_ADDED,
                                data=evidence_data,
                            )
                
                continue

            logger.error("Unhandled planner action (async)", extra={"action": str(action)})
            yield emit(EventType.ERROR, ContentType.MESSAGE, data="unhandled_action")

        # -------- Outline fallback --------
        if outline is None:
            try:
                outline = await asyncio.to_thread(
                    _generate_outline_fallback,
                    llm,
                    query,
                    evidence_bank,
                )
                paths.outline_path.write_text(outline.text, encoding="utf-8")
                logger.warning(
                    "No outline produced by planner; generated fallback outline via LLM (async).",
                    extra={"version": outline.version, "outline_path": str(paths.outline_path)},
                )
                yield emit(
                    EventType.LLM,
                    ContentType.OUTLINE_UPDATED,
                    data={"version": outline.version, "outline_path": str(paths.outline_path)},
                )
            except Exception as e:  # pragma: no cover - best-effort fallback
                logger.exception(
                    "Fallback outline generation failed (async); using minimal shell outline.",
                    extra={"error": str(e)},
                )
                outline = Outline(
                    text=(
                        "# Report\n\n"
                        "## References\n"
                        "<citation></citation>\n"
                    ),
                    version=1,
                )
                paths.outline_path.write_text(outline.text, encoding="utf-8")
                yield emit(
                    EventType.LLM,
                    ContentType.OUTLINE_UPDATED,
                    data={"version": outline.version, "outline_path": str(paths.outline_path)},
                )

        # -------- Outline evaluation (best-effort, async offload) --------
        try:
            repo_root = _repo_root()
            # NOTE: paper-related judgement templates are stored under docs/paper/.
            # Keep this path logic in sync with the docs layout.
            judge = OutlineJudge(
                llm=llm,
                prompt_template_path=repo_root / "docs" / "paper" / "PromptOutlineJudgement.md",
                criteria_path=repo_root / "docs" / "paper" / "judgementcriteria.md",
            )
            judge_result = await asyncio.to_thread(
                judge.judge,
                question=query,
                answer=outline.text,
            )
            out_path = paths.root / "outline_judgement.json"
            out_path.write_text(
                json.dumps(judge_result.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            yield emit(
                EventType.SYSTEM,
                ContentType.OUTLINE_JUDGE_RESULT,
                data={
                    "path": str(out_path),
                    "ratings": {k: v.rating for k, v in judge_result.results.items()},
                },
            )
        except Exception as e:
            yield emit(
                EventType.ERROR,
                ContentType.MESSAGE,
                data=str(e),
                metadata={"stage": "outline_judge_async"},
            )
            logger.exception("Outline judgement failed (async)")

        # -------- Writer (ReAct 风格，LLM 步骤 async offload) --------
        set_step("writer_async")
        writer = WriterAgentV2(llm=llm)
        logger.info("Writer started (async)", extra={"evidence_count": evidence_bank.count()})

        sections = _split_outline_sections(outline.text)
        report_parts: list[str] = []
        used_ids: set[str] = set()

        for sec_idx, (sec_title, sec_outline) in enumerate(sections, start=1):
            yield emit(
                EventType.SYSTEM,
                ContentType.WRITER_SECTION_START,
                data={"section_index": sec_idx, "title": sec_title},
            )
            set_step(f"writer_async:section:{sec_idx}")

            section_draft = ""
            tool_response: str | None = None
            section_citation_ids = extract_citation_ids(sec_outline)
            section_citation_ids = extract_citation_ids(sec_outline)
            section_citation_ids = extract_citation_ids(sec_outline)

            for step_in_section in range(settings.writer_max_steps_per_section):
                yield emit(
                    EventType.SYSTEM,
                    ContentType.WRITER_STEP,
                    data={"section_index": sec_idx, "step": step_in_section + 1},
                )

                if len(section_draft) > settings.writer_section_max_chars:
                    section_draft = section_draft[-settings.writer_section_max_chars :]

                try:
                    action = await writer.step_async(
                        WriterStepInputs(
                            query=query,
                            outline_text=f"## {sec_title}\n{sec_outline}",
                            draft=section_draft,
                            tool_response=tool_response,
                        )
                    )
                except Exception as e:
                    yield emit(
                        EventType.ERROR,
                        ContentType.MESSAGE,
                        data=str(e),
                        metadata={
                            "stage": "writer_async",
                            "section_index": sec_idx,
                            "step": step_in_section + 1,
                        },
                    )
                    logger.exception(
                        "Writer step failed (async)",
                        extra={"section_index": sec_idx, "step": step_in_section + 1},
                    )
                    break

                if isinstance(action, RetrieveAction):
                    # Prefer exact-id retrieval when citation ids are available,
                    # otherwise fall back to semantic/text retrieval.
                    top_k = action.top_k or settings.writer_retrieve_top_k
                    q = action.query or ""
                    yield emit(
                        EventType.TOOL,
                        ContentType.WRITER_RETRIEVE_QUERY,
                        data={"section_index": sec_idx, "query": q},
                    )
                    try:
                        # Resolve which evidence set to retrieve.
                        target_ids: list[str] | None = None
                        if action.citation_ids:
                            target_ids = action.citation_ids
                        elif section_citation_ids:
                            target_ids = section_citation_ids

                        retrieved_pairs: list[tuple[object, int]] = []
                        if target_ids:
                            evidences = evidence_bank.bulk_get(target_ids)
                            # Drop evidences already used in previous sections to reduce
                            # cross-section interference.
                            evidences = [
                                ev for ev in evidences if getattr(ev, "evidence_id", "") not in used_ids
                            ]
                            for ev in evidences[:top_k]:
                                retrieved_pairs.append((ev, 1))
                        else:
                            q = action.query or ""
                            retrieved_scored = await asyncio.to_thread(
                                evidence_bank.retrieve_scored,
                                query=q,
                                top_k=top_k,
                            )
                            # Filter out already-used evidences so they are not
                            # repeatedly surfaced in later sections.
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
                        yield emit(
                            EventType.ERROR,
                            ContentType.MESSAGE,
                            data=str(e),
                            metadata={"tool": "retrieve", "section_index": sec_idx},
                        )
                        logger.exception(
                            "Retrieve failed (async)",
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
                        # Explicit placeholder to indicate that no new evidence
                        # is available for this step.
                        tool_response = "<tool_response><material>NO_NEW_EVIDENCE</material></tool_response>"
                    yield emit(
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
                    yield emit(
                        EventType.LLM,
                        ContentType.WRITER_WRITE,
                        data={"section_index": sec_idx, "chars": len(piece)},
                    )
                    continue

                if isinstance(action, WriterTerminateAction):
                    yield emit(
                        EventType.SYSTEM,
                        ContentType.WRITER_TERMINATE,
                        data={"section_index": sec_idx, "reason": action.reason},
                    )
                    break

            report_parts.append(f"## {sec_title}\n\n{section_draft.strip()}".strip())
            yield emit(
                EventType.SYSTEM,
                ContentType.WRITER_SECTION_DONE,
                data={"section_index": sec_idx, "title": sec_title, "chars": len(section_draft)},
            )

        # -------- References (重用现有 WriterAgent 的引用渲染逻辑) --------
        evidences_by_id = {e.evidence_id: e for e in evidence_bank.list_all()}
        refs = WriterAgent._render_references(sorted(used_ids), evidences_by_id)
        report = ("\n\n".join(report_parts).strip() + "\n\n" + refs).strip()
        report = _clean_report_text(report)
        paths.report_path.write_text(report, encoding="utf-8")
        logger.info("Report written (async)", extra={"report_path": str(paths.report_path)})
        yield emit(
            EventType.SYSTEM,
            ContentType.REPORT_DONE,
            data={
                "report_path": str(paths.report_path),
                "outline_path": str(paths.outline_path),
                "events_path": str(paths.events_path),
                "run_root": str(paths.root),
            },
        )


def _format_tool_response(evidences: list[object], *, max_items: int) -> str:
    parts: list[str] = []
    parts.append("<tool_response>")
    parts.append("<material>")
    for ev in evidences:
        try:
            eid = ev.evidence_id
            parts.append(f"<{eid}>")
            parts.append(f"Summary: {ev.summary}")
            for it in (ev.evidence_items or [])[:max_items]:
                parts.append(f"- {it.type}: {it.content}")
            parts.append(f"URL: {ev.source.url}")
            parts.append(f"</{eid}>")
        except Exception:
            continue
    parts.append("</material>")
    parts.append("</tool_response>")
    return "\n".join(parts)


def _prune_retrieved(
    retrieved_scored: list[tuple[object, int]],
    *,
    max_evidences: int,
    evidence_items_per_evidence: int,
    max_chars: int,
) -> tuple[list[object], set[str]]:
    """Prune and de-duplicate retrieved evidences for tool_response."""

    out: list[object] = []
    used_ids: set[str] = set()
    seen_item_text: set[str] = set()

    # Conservative string budget accounting to prevent huge tool_response.
    budget = max_chars

    for ev, _score in retrieved_scored[:max_evidences]:
        try:
            eid = ev.evidence_id
            if eid in used_ids:
                continue
            used_ids.add(eid)

            # Shallow copy-like pruning of evidence_items
            pruned_items = []
            for it in (ev.evidence_items or [])[: max(0, evidence_items_per_evidence) * 3]:
                key = (it.content or "").strip().lower()
                if not key or key in seen_item_text:
                    continue
                seen_item_text.add(key)
                pruned_items.append(it)
                if len(pruned_items) >= evidence_items_per_evidence:
                    break

            # Estimate cost; if too large, stop.
            approx = len(getattr(ev, "summary", "") or "") + sum(len(it.content or "") for it in pruned_items)
            approx += 200
            if budget - approx <= 0:
                break
            budget -= approx

            # Mutate a lightweight view object by setting evidence_items if possible.
            try:
                ev = ev.model_copy(update={"evidence_items": pruned_items})
            except Exception:
                # If not a pydantic model, fall back to keeping it as-is.
                pass

            out.append(ev)
        except Exception:
            continue

    return out, used_ids


def _generate_outline_fallback(llm: LLMClient, query: str, evidence_bank: EvidenceBank) -> Outline:
    """Best-effort fallback: 直接由 LLM 生成一个中文长篇大纲。

    触发条件：planner 在所有步骤内都未产出任何 outline。
    逻辑：
        - 汇总最近若干条 evidence 的摘要作为上下文；
        - 用一个独立的 system 提示词，要求模型一次性输出 <write_outline>...</write_outline>，
          且大纲为中文、结构完整、带 citation 标签。
    """

    evidences = evidence_bank.list_all()[-10:]
    ctx_lines: list[str] = []
    for ev in evidences:
        try:
            ctx_lines.append(f"- 证据ID: {ev.evidence_id}")
            ctx_lines.append(f"  URL: {ev.source.url}")
            if ev.summary:
                ctx_lines.append(f"  摘要: {ev.summary[:400]}")
        except Exception:
            continue
    ctx_block = "\n".join(ctx_lines) if ctx_lines else "<暂无结构化证据，仅有原始网页文本。>"

    system_prompt = (
        "你现在处于 WebWeaver 的“补救模式”，需要**直接生成一份中文长篇学术报告的大纲**。\n"
        "注意：\n"
        "- 忽略之前 Planner 的所有决策，仅根据“研究问题 + 证据摘要”自行设计结构合理的大纲；\n"
        "- 大纲必须使用**简体中文**书写，可以保留必要的英文专有名词和文献标题；\n"
        "- 输出时**只能**使用一次 `<write_outline>...</write_outline>` 标签包裹完整大纲，不要输出任何其他内容；\n"
        "- 大纲结构至少应包含：引言、相关工作/背景、方法、实验或案例分析、结果与讨论、安全与伦理/风险分析、未来工作/展望、结论、参考文献；\n"
        "- 在关键小节中按 WebWeaver 的约定加入 `<citation>ev_0001,ev_0002</citation>` 这样的引用标记（若证据 ID 存在）；\n"
        "- 目标是支撑一篇**长篇中文论文**，所以每个二级标题下应包含多个三级标题和要点说明。"
    )

    user_prompt = (
        f"研究问题（原始 Query）：\n{query}\n\n"
        "以下是当前证据库中部分证据的摘要（可能来自 Tavily 搜索 + 网页解析）：\n"
        f"{ctx_block}\n\n"
        "请你综合以上信息，直接给出完整的大纲，严格放在 `<write_outline>...</write_outline>` 中输出："
    )

    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_prompt),
    ]
    raw = llm.complete(messages, temperature=0.3)

    m = re.search(r"<write_outline>(?P<body>.*?)</write_outline>", raw, re.DOTALL)
    if m:
        outline_text = m.group("body").strip()
    else:
        outline_text = raw.strip()

    if not outline_text:
        outline_text = "# Report\n\n## 引言\n...\n\n## 参考文献（References）\n<citation></citation>\n"

    return Outline(text=outline_text, version=1)


def _clean_report_text(text: str) -> str:
    """Post-process the final report to remove tool-call noise.

    This function strips out stray `retrieve` lines and bare JSON argument
    blocks that occasionally leak into the written report when the writer
    model forgets to wrap them in <tool_call> tags.
    """

    lines = text.splitlines()
    cleaned: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue

        # Drop bare 'retrieve' lines.
        if stripped.lower() == "retrieve":
            continue

        # Drop lines that are *just* a JSON object (likely tool args),
        # but keep JSON-like text if parsing fails.
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                json.loads(stripped)
                continue
            except Exception:
                pass

        cleaned.append(line)

    return "\n".join(cleaned).strip()


def _split_outline_sections(outline_text: str) -> list[tuple[str, str]]:
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


def run_research_stream(*, query: str, settings: Settings) -> Iterator[RunEvent]:
    """Run the full workflow and yield events for streaming.

    Events are recorded to JSONL for replay.
    """

    run_id, run_root = _prepare_run_dir(settings.artifacts_dir)
    paths = RunPaths(root=run_root)
    recorder = FileEventRecorder(paths.events_path)

    redis_recorder: RedisEventRecorder | None = None
    if settings.redis_enabled:
        redis_recorder = RedisEventRecorder(
            redis_url=settings.redis_url,
            key_prefix=settings.redis_key_prefix,
            run_id=run_id,
        )
        redis_recorder.set_meta({"run_root": str(paths.root)})

    seq = 0

    def emit(
        event_type: EventType,
        content_type: ContentType,
        data: str | dict | list | None = None,
        *,
        metadata: dict[str, str | int | float | bool | None] | None = None,
    ) -> RunEvent:
        nonlocal seq
        seq += 1
        ev = RunEvent(
            run_id=run_id,
            seq=seq,
            event_type=event_type,
            content_type=content_type,
            data=data,
            metadata=dict(metadata or {}),
        )
        recorder.append(ev)
        if redis_recorder is not None:
            redis_recorder.append(ev)
        return ev

    with run_context(run_id=run_id, step="init"):
        logger.info("Run started", extra={"query": query, "artifacts": str(paths.root)})
        yield emit(EventType.SYSTEM, ContentType.MESSAGE, "run_started", metadata={"query": query})

        llm = LLMClient(settings)
        evidence_bank = EvidenceBank(paths.evidence_root)

        search_provider = get_search_provider(settings)
        url_filter = UrlFilter(llm=llm)
        fetcher = PageFetcher(settings)
        parser = PageParser()
        summarizer = Summarizer(llm=llm)
        extractor = EvidenceExtractor(llm=llm)
        planner = PlannerAgent(llm=llm)

        outline: Outline | None = None

        for step_idx in range(settings.planner_max_steps):
            set_step(f"planner:{step_idx + 1}")
            logger.info(
                "Planner step start",
                extra={"step_index": step_idx + 1, "max_steps": settings.planner_max_steps},
            )
            yield emit(
                EventType.SYSTEM,
                ContentType.PLANNER_STEP,
                data={"step": step_idx + 1, "max_steps": settings.planner_max_steps},
            )

            evidences = evidence_bank.list_all()
            action = planner.step(
                PlannerInputs(
                    query=query,
                    outline=outline,
                    evidences=evidences,
                    step_index=step_idx,
                    max_steps=settings.planner_max_steps,
                )
            )

            if isinstance(action, TerminateAction):
                # 如果在尚未产生任何大纲时就请求终止，视为异常情况，转为一次保守的搜索动作，
                # 避免直接退回到空大纲，导致后续 writer 无内容可写。
                if outline is None:
                    logger.warning(
                        "Planner requested early terminate without outline; "
                        "falling back to SearchAction for initial evidence.",
                        extra={"reason": action.reason},
                    )
                    action = SearchAction(
                        queries=[query],
                        goal="Collect initial evidence in Chinese for the research outline.",
                    )
                else:
                    logger.info("Planner terminated", extra={"reason": action.reason})
                    yield emit(EventType.SYSTEM, ContentType.PLANNER_TERMINATE, data=action.reason)
                    break

            if isinstance(action, WriteOutlineAction):
                outline = Outline(
                    text=action.outline_text,
                    version=(outline.version + 1 if outline else 1),
                )
                paths.outline_path.write_text(outline.text, encoding="utf-8")
                logger.info(
                    "Outline updated",
                    extra={"version": outline.version, "outline_path": str(paths.outline_path)},
                )
                yield emit(
                    EventType.LLM,
                    ContentType.OUTLINE_UPDATED,
                    data={"version": outline.version, "outline_path": str(paths.outline_path)},
                )
                continue

            if isinstance(action, SearchAction):
                logger.info(
                    "Planner search action",
                    extra={"queries": action.queries[: settings.planner_max_queries_per_step]},
                )
                for q in action.queries[: settings.planner_max_queries_per_step]:
                    yield emit(EventType.TOOL, ContentType.SEARCH_QUERY, data=q)
                    try:
                        results = search_provider.search(q, max_results=settings.search_max_results)
                    except WebSearchError as e:
                        yield emit(
                            EventType.ERROR,
                            ContentType.MESSAGE,
                            data=str(e),
                            metadata={"tool": "web_search", "provider": settings.search_provider, "query": q},
                        )
                        logger.exception(
                            "Search provider failed",
                            extra={"provider": settings.search_provider, "query": q},
                        )
                        results = []
                    except Exception as e:
                        yield emit(
                            EventType.ERROR,
                            ContentType.MESSAGE,
                            data=str(e),
                            metadata={"tool": "web_search", "provider": settings.search_provider, "query": q},
                        )
                        logger.exception(
                            "Unexpected search error",
                            extra={"provider": settings.search_provider, "query": q},
                        )
                        results = []
                    logger.info(
                        "Search results",
                        extra={"query": q, "results": len(results), "provider": settings.search_provider},
                    )
                    yield emit(
                        EventType.TOOL,
                        ContentType.SEARCH_RESULTS,
                        data=[r.model_dump(mode="json") for r in results],
                    )

                    try:
                        selected = url_filter.select_urls(
                            q, results, max_urls=settings.planner_max_urls_per_query
                        )
                    except Exception as e:
                        yield emit(
                            EventType.ERROR,
                            ContentType.MESSAGE,
                            data=str(e),
                            metadata={"tool": "url_filter", "query": q},
                        )
                        logger.exception("URL filter failed; fallback to top results", extra={"query": q})
                        selected = results[: settings.planner_max_urls_per_query]
                    logger.info(
                        "URLs selected",
                        extra={"query": q, "selected": len(selected)},
                    )

                    for r in selected:
                        yield emit(EventType.TOOL, ContentType.URL_SELECTED, data=str(r.url))
                        try:
                            fetched = fetcher.fetch(str(r.url))
                            html = fetched.content.decode("utf-8", errors="ignore")
                            doc = parser.parse_html(
                                str(r.url), html, content_type=fetched.content_type
                            )

                            summary = summarizer.summarize(query=query, text=doc.text)
                            if summary.strip().upper().startswith("NOT RELEVANT"):
                                logger.info("Page not relevant", extra={"url": str(r.url)})
                                continue

                            items = extractor.extract(query=query, text=doc.text, max_items=8)
                            source = EvidenceSource(url=str(r.url), title=doc.title)
                            ev = evidence_bank.add(
                                query=q,
                                source=source,
                                summary=summary,
                                evidence_items=items,
                                raw_text=doc.text,
                                tags=[],
                            )
                            logger.info(
                                "Evidence added",
                                extra={"evidence_id": ev.evidence_id, "url": str(ev.source.url)},
                            )
                            yield emit(
                                EventType.TOOL,
                                ContentType.EVIDENCE_ADDED,
                                data={
                                    "evidence_id": ev.evidence_id,
                                    "url": str(ev.source.url),
                                },
                            )
                        except Exception as e:
                            yield emit(
                                EventType.ERROR,
                                ContentType.MESSAGE,
                                data=str(e),
                                metadata={"url": str(r.url)},
                            )
                            logger.exception(
                                "Failed processing url",
                                extra={"url": str(r.url)},
                            )
                            continue

                continue

            logger.error("Unhandled action", extra={"action": str(action)})
            yield emit(EventType.ERROR, ContentType.MESSAGE, data="unhandled_action")

    if outline is None:
        try:
            outline = _generate_outline_fallback(llm=llm, query=query, evidence_bank=evidence_bank)
            paths.outline_path.write_text(outline.text, encoding="utf-8")
            logger.warning(
                "No outline produced by planner; generated fallback outline via LLM.",
                extra={"version": outline.version, "outline_path": str(paths.outline_path)},
            )
            yield emit(
                EventType.LLM,
                ContentType.OUTLINE_UPDATED,
                data={"version": outline.version, "outline_path": str(paths.outline_path)},
            )
        except Exception as e:  # pragma: no cover - best-effort fallback
            logger.exception(
                "Fallback outline generation failed; using minimal shell outline.",
                extra={"error": str(e)},
            )
            outline = Outline(
                text=(
                    "# Report\n\n"
                    "## References\n"
                    "<citation></citation>\n"
                ),
                version=1,
            )
            paths.outline_path.write_text(outline.text, encoding="utf-8")
            yield emit(
                EventType.LLM,
                ContentType.OUTLINE_UPDATED,
                data={"version": outline.version, "outline_path": str(paths.outline_path)},
            )

        # Outline evaluation (production: best-effort, should not break runs)
        try:
            repo_root = _repo_root()
            # NOTE: paper-related judgement templates are stored under docs/paper/.
            # Keep this path logic in sync with the docs layout.
            judge = OutlineJudge(
                llm=llm,
                prompt_template_path=repo_root / "docs" / "paper" / "PromptOutlineJudgement.md",
                criteria_path=repo_root / "docs" / "paper" / "judgementcriteria.md",
            )
            judge_result = judge.judge(question=query, answer=outline.text)
            out_path = paths.root / "outline_judgement.json"
            out_path.write_text(
                json.dumps(judge_result.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            yield emit(
                EventType.SYSTEM,
                ContentType.OUTLINE_JUDGE_RESULT,
                data={
                    "path": str(out_path),
                    "ratings": {k: v.rating for k, v in judge_result.results.items()},
                },
            )
        except Exception as e:
            yield emit(
                EventType.ERROR,
                ContentType.MESSAGE,
                data=str(e),
                metadata={"stage": "outline_judge"},
            )
            logger.exception("Outline judgement failed")

        set_step("writer")
        writer = WriterAgentV2(llm=llm)
        logger.info("Writer started", extra={"evidence_count": evidence_bank.count()})

        sections = _split_outline_sections(outline.text)
        report_parts: list[str] = []
        used_ids: set[str] = set()

        for sec_idx, (sec_title, sec_outline) in enumerate(sections, start=1):
            yield emit(
                EventType.SYSTEM,
                ContentType.WRITER_SECTION_START,
                data={"section_index": sec_idx, "title": sec_title},
            )
            set_step(f"writer:section:{sec_idx}")

            section_draft = ""
            tool_response: str | None = None
            section_citation_ids = extract_citation_ids(sec_outline)

            for step_in_section in range(settings.writer_max_steps_per_section):
                yield emit(
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
                    yield emit(
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
                    # Prefer exact-id retrieval when citation ids are available,
                    # otherwise fall back to semantic/text retrieval.
                    top_k = action.top_k or settings.writer_retrieve_top_k
                    q = action.query or ""
                    yield emit(
                        EventType.TOOL,
                        ContentType.WRITER_RETRIEVE_QUERY,
                        data={"section_index": sec_idx, "query": q},
                    )
                    try:
                        # Resolve which evidence set to retrieve.
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
                        yield emit(
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
                    yield emit(
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
                    yield emit(
                        EventType.LLM,
                        ContentType.WRITER_WRITE,
                        data={"section_index": sec_idx, "chars": len(piece)},
                    )
                    continue

                if isinstance(action, WriterTerminateAction):
                    yield emit(
                        EventType.SYSTEM,
                        ContentType.WRITER_TERMINATE,
                        data={"section_index": sec_idx, "reason": action.reason},
                    )
                    break

            report_parts.append(f"## {sec_title}\n\n{section_draft.strip()}".strip())
            yield emit(
                EventType.SYSTEM,
                ContentType.WRITER_SECTION_DONE,
                data={"section_index": sec_idx, "title": sec_title, "chars": len(section_draft)},
            )

        evidences_by_id = {e.evidence_id: e for e in evidence_bank.list_all()}
        refs = WriterAgent._render_references(sorted(used_ids), evidences_by_id)
        report = ("\n\n".join(report_parts).strip() + "\n\n" + refs).strip()
        report = _clean_report_text(report)
        paths.report_path.write_text(report, encoding="utf-8")
        logger.info("Report written", extra={"report_path": str(paths.report_path)})
        yield emit(
            EventType.SYSTEM,
            ContentType.REPORT_DONE,
            data={
                "report_path": str(paths.report_path),
                "outline_path": str(paths.outline_path),
                "events_path": str(paths.events_path),
                "run_root": str(paths.root),
            },
        )


def replay_run(*, run_id: str, artifacts_dir: Path) -> Iterator[RunEvent]:
    """Replay a run from recorded events."""

    # Run directory naming matches _prepare_run_dir
    run_dir = artifacts_dir / f"run_{run_id}"
    events_path = run_dir / "events.jsonl"

    file_events = iter_events(events_path)
    if file_events:
        for ev in file_events:
            yield ev
        return

    # Fallback to Redis if file-based events are not available.
    try:
        tmp_settings = Settings()  # env-based
        if tmp_settings.redis_enabled:
            rr = RedisEventRecorder(
                redis_url=tmp_settings.redis_url,
                key_prefix=tmp_settings.redis_key_prefix,
                run_id=run_id,
            )
            for ev in rr.iter_events():
                yield ev
    except Exception:
        return


def _prepare_run_dir(base: Path) -> tuple[str, Path]:
    base.mkdir(parents=True, exist_ok=True)
    # Run id is time-based for readability plus a short random suffix to avoid collisions.
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    run_id = f"{ts}_{suffix}"
    run_dir = base / f"run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_id, run_dir
