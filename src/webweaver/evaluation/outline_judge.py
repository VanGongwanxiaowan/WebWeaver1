from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from webweaver.llm.client import ChatMessage, LLMClient
from webweaver.logging import get_logger

logger = get_logger(__name__)


class OutlineJudgeCriterion(BaseModel):
    name: str
    description: str


class OutlineJudgeItemResult(BaseModel):
    rating: int = Field(ge=0, le=10)
    justification: str


class OutlineJudgeResult(BaseModel):
    question: str
    answer: str
    results: dict[str, OutlineJudgeItemResult] = Field(default_factory=dict)


@dataclass(frozen=True)
class OutlineJudge:
    llm: LLMClient
    prompt_template_path: Path
    criteria_path: Path

    def load_criteria(self) -> list[OutlineJudgeCriterion]:
        """Load judgement criteria.

        Preferred format is a strict JSON array:
        `[{"name": "...", "description": "..."}, ...]`

        For backward compatibility, we also accept a JSONL-style file where each line
        is a single JSON object.
        """

        text = self.criteria_path.read_text(encoding="utf-8")
        raw = text.strip()
        if not raw:
            return []

        # Preferred: strict JSON array (or object)
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [OutlineJudgeCriterion.model_validate(x) for x in data]
            if isinstance(data, dict):
                return [OutlineJudgeCriterion.model_validate(data)]
        except Exception:
            pass

        # Fallback: JSONL (one object per line), optionally mixed with other text.
        criteria: list[OutlineJudgeCriterion] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
                criteria.append(OutlineJudgeCriterion.model_validate(data))
            except Exception:
                logger.warning("Failed parsing criterion line; skipping")
                continue
        return criteria

    def _render_prompt(self, *, criterion: OutlineJudgeCriterion, question: str, answer: str) -> str:
        template = self.prompt_template_path.read_text(encoding="utf-8")
        rendered = template
        rendered = rendered.replace("{question}", question)
        rendered = rendered.replace("{answer}", answer)
        rendered = rendered.replace("{criterion[’name’]}", criterion.name)
        rendered = rendered.replace("{criterion[’description’]}", criterion.description)
        rendered = rendered.replace("{criterion['name']}", criterion.name)
        rendered = rendered.replace("{criterion['description']}", criterion.description)
        return rendered

    def judge(self, *, question: str, answer: str) -> OutlineJudgeResult:
        criteria = self.load_criteria()
        out = OutlineJudgeResult(question=question, answer=answer)
        if not criteria:
            logger.warning("No criteria loaded; skipping judgement")
            return out

        for c in criteria:
            prompt = self._render_prompt(criterion=c, question=question, answer=answer)
            messages = [
                ChatMessage(role="system", content="You are a strict evaluator."),
                ChatMessage(role="user", content=prompt),
            ]

            raw = self.llm.complete(messages, temperature=0.0)
            parsed: OutlineJudgeItemResult | None = None
            try:
                data = json.loads(raw)
                parsed = OutlineJudgeItemResult.model_validate(data)
            except Exception:
                # try to salvage JSON from noisy outputs
                try:
                    start = raw.find("{")
                    end = raw.rfind("}")
                    if start != -1 and end != -1 and end > start:
                        data = json.loads(raw[start : end + 1])
                        parsed = OutlineJudgeItemResult.model_validate(data)
                except Exception:
                    parsed = None

            if parsed is None:
                logger.warning(
                    "Outline judge parse failed",
                    extra={"criterion": c.name, "raw_preview": raw[:200]},
                )
                continue

            out.results[c.name] = parsed
            logger.info(
                "Outline judged",
                extra={"criterion": c.name, "rating": parsed.rating},
            )

        return out
