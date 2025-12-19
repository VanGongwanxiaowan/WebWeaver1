"""Planner agent.

The planner iteratively alternates between evidence acquisition and outline optimization.
It produces one of three actions: search / write_outline / terminate.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass

from webweaver.agents.actions import PlannerAction, SearchAction, TerminateAction, WriteOutlineAction
from webweaver.llm.client import ChatMessage, LLMClient
from webweaver.logging import get_logger
from webweaver.models.evidence import Evidence
from webweaver.models.outline import Outline
from webweaver.prompts import PLANNER_SYSTEM_PROMPT
from webweaver.utils.tags import parse_tool_call_payload

logger = get_logger(__name__)

_TOOL_CALL_OPEN = "<" + "tool_call" + ">"
_TOOL_CALL_CLOSE = "</" + "tool_call" + ">"
_TOOL_CALL_RE = re.compile(
    r"{}\s*(?P<json>\{{.*?\}})\s*{}".format(_TOOL_CALL_OPEN, _TOOL_CALL_CLOSE),
    re.DOTALL,
)
_WRITE_OUTLINE_RE = re.compile(r"<write_outline>(?P<body>.*?)</write_outline>", re.DOTALL)
_TERMINATE_RE = re.compile(r"<terminate>(?P<body>.*?)</terminate>", re.DOTALL)


@dataclass(frozen=True)
class PlannerInputs:
    """Inputs for one planner step."""

    query: str
    outline: Outline | None
    evidences: list[Evidence]
    step_index: int
    max_steps: int


class PlannerAgent:
    """WebWeaver Planner agent."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def step(self, inputs: PlannerInputs) -> PlannerAction:
        """Run one planner decision step (synchronous)."""

        prompt = self._build_prompt(inputs)
        messages = [
            ChatMessage(
                role="system",
                content=PLANNER_SYSTEM_PROMPT,
            ),
            ChatMessage(role="user", content=prompt),
        ]

        # Use deterministic decoding to reduce chances of malformed tags.
        raw = self._llm.complete(messages, temperature=0.0)
        action = self._parse_action(raw)
        return action

    async def step_async(self, inputs: PlannerInputs) -> PlannerAction:
        """Run one planner decision step asynchronously.

        This method is a drop-in async variant of :meth:`step` that offloads
        the blocking LLM call to a thread, so it will not block the event loop
        and can be used in high-concurrency async workflows.
        """

        prompt = self._build_prompt(inputs)
        messages = [
            ChatMessage(
                role="system",
                content=PLANNER_SYSTEM_PROMPT,
            ),
            ChatMessage(role="user", content=prompt),
        ]

        # If the LLM client later gains a native async API (e.g. `acomplete`),
        # we can switch to that here while keeping the public interface stable.
        # Use deterministic decoding to reduce chances of malformed tags.
        raw = await asyncio.to_thread(self._llm.complete, messages, temperature=0.0)
        action = self._parse_action(raw)
        return action

    @staticmethod
    def _build_prompt(inputs: PlannerInputs) -> str:
        lines: list[str] = []
        lines.append(f"User Query: {inputs.query}")
        lines.append(f"Planning Step: {inputs.step_index + 1}/{inputs.max_steps}")
        lines.append("")

        if inputs.outline is None:
            lines.append("Current Outline: <none>")
        else:
            lines.append("Current Outline:")
            lines.append(inputs.outline.text)
        lines.append("")

        lines.append("Evidence Bank Summaries (id, url, summary):")
        if not inputs.evidences:
            lines.append("<empty>")
        else:
            for ev in inputs.evidences[-20:]:
                lines.append(f"- {ev.evidence_id} | {ev.source.url}")
                lines.append(f"  Summary: {ev.summary[:400]}")
        lines.append("")

        # 基于步骤数和证据数量给出明确的决策指导
        evidence_count = len(inputs.evidences)
        step_num = inputs.step_index + 1
        
        decision_guidance = []
        
        # 强制写初始大纲的条件
        if inputs.outline is None:
            if step_num >= 4 or evidence_count >= 3:
                decision_guidance.append(
                    f"⚠️ **重要**：当前是第 {step_num} 步，证据库中有 {evidence_count} 条证据。"
                    f"根据渐进式大纲生成策略，**你必须**使用 `<write_outline>` 输出一个初始大纲，"
                    f"即使证据还不够充分。初始大纲应该包含至少 5-7 个主要章节（引言、相关工作、方法、"
                    f"实验设计、实验结果与讨论、局限性、未来工作、结论、参考文献），并在已有证据的章节中插入 `<citation>` 标签。"
                )
            else:
                decision_guidance.append(
                    f"当前是第 {step_num} 步，证据库中有 {evidence_count} 条证据。"
                    f"建议继续使用 `search` 收集更多证据（目标：至少 3-5 条）。"
                )
        else:
            # 已有大纲，判断是否需要更新或终止
            if step_num >= inputs.max_steps - 2:
                decision_guidance.append(
                    f"⚠️ **重要**：当前是第 {step_num}/{inputs.max_steps} 步，接近最大步数。"
                    f"如果大纲已经足够完善（包含所有主要章节、有充分的 `<citation>` 标签、有参考文献部分），"
                    f"请使用 `<terminate>` 结束规划。否则，使用 `<write_outline>` 更新大纲以补充缺失部分。"
                )
            elif evidence_count >= 8:
                decision_guidance.append(
                    f"当前有 {evidence_count} 条证据，证据已较为充分。"
                    f"建议使用 `<write_outline>` 更新大纲，补充新的章节、细化子节、添加更多 `<citation>` 标签。"
                )
            else:
                decision_guidance.append(
                    f"当前有 {evidence_count} 条证据。可以继续使用 `search` 补充证据，"
                    f"或使用 `<write_outline>` 更新大纲以反映已有证据。"
                )
        
        decision_guidance.append(
            "记住：采用「先写初始大纲，再迭代优化」的策略，不要等到证据完全充分才写大纲。"
        )
        
        lines.append("决策指导：")
        lines.extend(decision_guidance)
        lines.append("")
        lines.append(
            "请根据上述指导，选择以下三种动作之一："
            "1) `search` - 搜索更多证据；"
            "2) `<write_outline>...</write_outline>` - 输出或更新大纲；"
            "3) `<terminate>...</terminate>` - 终止规划（仅当大纲已充分完备时）。"
        )
        return "\n".join(lines)

    @staticmethod
    def _parse_action(raw: str) -> PlannerAction:
        raw = raw.strip()

        # 优先解析 <write_outline>，避免因为同时包含 <terminate> 而过早终止
        m_outline = _WRITE_OUTLINE_RE.search(raw)
        if m_outline:
            body = m_outline.group("body").strip()
            return WriteOutlineAction(outline_text=body)

        # 仅在未检测到 write_outline 时，再检查是否为真正的终止信号
        m_term = _TERMINATE_RE.search(raw)
        if m_term:
            reason = m_term.group("body").strip() or "terminated"
            return TerminateAction(reason=reason)

        # 更稳健的 tool_call 解析：支持 <tool_call>{...}</tool_call> 或裸 JSON
        data = parse_tool_call_payload(raw)
        if data:
            if data.get("name") != "search":
                return TerminateAction(reason="unsupported_tool")
            args = data.get("arguments") or {}
            queries = args.get("query") or []
            if isinstance(queries, str):
                queries = [queries]
            goal = args.get("goal") or "collect evidence"
            queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
            if not queries:
                return TerminateAction(reason="no_queries")
            return SearchAction(queries=queries, goal=str(goal))

        # Fallback: if no valid tags are found but there is non-empty content,
        # interpret the whole output as an outline instead of terminating.
        if raw:
            logger.warning("Planner output missing expected tags; treating raw output as outline.")
            return WriteOutlineAction(outline_text=raw)

        return TerminateAction(reason="unparseable_output")
