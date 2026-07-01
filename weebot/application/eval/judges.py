"""Judge implementations for the evaluation framework.

ModelJudge — LLM-based judge that scores output against criteria.
ScoreJudge — deterministic judge (exact match, substring, regex).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from weebot.application.ports.judge_port import CriterionScore, JudgePort, JudgeVerdict
from weebot.application.ports.llm_port import LLMPort
from weebot.config.constants import TEMPERATURE_DETERMINISTIC

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM_PROMPT = """\
You are an expert evaluator. Given a task description, the agent's output,
and a list of criteria, score the output on each criterion from 0 to 10.

For each criterion:
- 9-10: Excellent — fully meets the criterion
- 7-8: Good — mostly meets it, minor gaps
- 5-6: Adequate — partially meets it, significant gaps
- 3-4: Poor — barely addresses it
- 1-2: Very poor — fails to address it
- 0: Not addressed at all

Respond with JSON:
{
  "criteria": [
    {"name": "<criterion>", "score": <0-10>, "reasoning": "<one sentence>"},
    ...
  ],
  "overall_score": <0-10>,
  "reasoning": "<one sentence summary>"
}
"""


class ModelJudge(JudgePort):
    """LLM-based judge that scores output against criteria.

    Args:
        llm: LLMPort instance for the evaluation call.
        model: Model ID for the evaluation call (defaults to MODEL_BUDGET).
    """

    def __init__(
        self,
        llm: LLMPort,
        model: Optional[str] = None,
    ) -> None:
        self._llm = llm
        self._model = model

    async def judge(
        self,
        task_description: str,
        output: str,
        criteria: list[str],
        context: str = "",
    ) -> JudgeVerdict:
        criteria_text = ", ".join(criteria) if criteria else "overall quality"
        prompt = (
            f"Task: {task_description}\n\n"
            f"Output:\n{output[:3000]}\n\n"
            f"Criteria: {criteria_text}\n"
        )
        if context:
            prompt += f"\nExpected output / context:\n{context[:1000]}\n"

        try:
            resp = await self._llm.chat(
                messages=[
                    {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model=self._model,
                temperature=TEMPERATURE_DETERMINISTIC,
            )
            data = json.loads(resp.content or "{}")
            criterion_scores = data.get("criteria", [])
            parsed_criteria = [
                CriterionScore(
                    name=c.get("name", "unknown"),
                    score=float(c.get("score", 0)),
                    reasoning=c.get("reasoning", ""),
                )
                for c in criterion_scores
            ]
            overall = float(data.get("overall_score", 0)) / 10.0
            reasoning = data.get("reasoning", "")

            return JudgeVerdict(
                criteria=parsed_criteria,
                overall_score=min(overall, 1.0),
                passed=overall >= 0.6,
                reasoning=reasoning,
            )
        except Exception as exc:
            logger.warning("ModelJudge failed: %s — returning default fail verdict", exc)
            return JudgeVerdict(
                overall_score=0.0, passed=False,
                reasoning=f"judge failed: {exc}",
            )


class ScoreJudge(JudgePort):
    """Deterministic judge that scores output by exact/partial matching.

    Args:
        pass_ratio: Fraction of criteria that must match to pass (default 1.0).
    """

    def __init__(self, pass_ratio: float = 1.0) -> None:
        self._pass_ratio = pass_ratio

    async def judge(
        self,
        task_description: str,
        output: str,
        criteria: list[str],
        context: str = "",
    ) -> JudgeVerdict:
        if not criteria:
            # No criteria given — check that output is non-empty
            score = 10.0 if output.strip() else 0.0
            passed = bool(output.strip())
            return JudgeVerdict(
                criteria=[CriterionScore("has_output", score, "")],
                overall_score=score / 10.0,
                passed=passed,
                reasoning="non-empty output" if passed else "empty output",
            )

        output_lower = output.lower()
        criterion_scores: list[CriterionScore] = []
        matches = 0

        for criterion in criteria:
            if criterion.startswith("regex:"):
                pattern = criterion[6:]
                matched = bool(re.search(pattern, output, re.IGNORECASE))
            else:
                matched = criterion.lower() in output_lower

            score = 10.0 if matched else 0.0
            if matched:
                matches += 1
            criterion_scores.append(CriterionScore(
                name=criterion[:30],
                score=score,
                reasoning="found" if matched else "not found",
            ))

        match_ratio = matches / len(criteria) if criteria else 0.0
        overall_score = match_ratio
        passed = match_ratio >= self._pass_ratio

        return JudgeVerdict(
            criteria=criterion_scores,
            overall_score=overall_score,
            passed=passed,
            reasoning=f"{matches}/{len(criteria)} criteria matched",
        )
