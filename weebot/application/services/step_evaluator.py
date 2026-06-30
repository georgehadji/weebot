"""LLM-based step progress evaluator.

Evaluates whether a step's output advances the plan toward its goal.
Fails open on LLM errors so execution never blocks on evaluation.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.step_evaluator_port import StepEvaluation, StepEvaluatorPort
from weebot.config.constants import TEMPERATURE_DETERMINISTIC
from weebot.domain.models.plan import Plan, Step

logger = logging.getLogger(__name__)

_EVAL_PROMPT = """\
You are evaluating whether an agent's step output advances the plan toward its goal.

Plan goal: {plan_goal}
Current step: {step_description}
Step output:
{output}

Previous step outputs (most recent first):
{previous_outputs}

Score the step output from 0.0 to 1.0:
- 1.0: Step fully completed, clear progress toward goal
- 0.7+: Substantial progress, minor gaps
- 0.4-0.7: Partial progress, significant gaps
- 0.0-0.4: No meaningful progress or regression

Respond with JSON:
{{"score": float, "regression_detected": bool, "reasoning": "one sentence", "recommendations": ["if any"]}}
"""


class NoOpStepEvaluator(StepEvaluatorPort):
    """Step evaluator that always passes.

    Used as the default when no evaluator is configured.
    """

    async def evaluate(
        self,
        step: Step,
        output: str,
        plan: Plan,
        previous_outputs: list[str],
    ) -> StepEvaluation:
        return StepEvaluation(
            step_id=step.id,
            score=1.0,
            passed=True,
            regression_detected=False,
            reasoning="no-op evaluator",
        )


class LLMStepEvaluator(StepEvaluatorPort):
    """LLM-based step evaluator that scores step output against plan goals.

    Args:
        llm: LLMPort instance for the evaluation call.
        model: Model ID for the evaluation call (defaults to MODEL_BUDGET).
        threshold: Minimum score to pass (default 0.4).
    """

    def __init__(
        self,
        llm: LLMPort,
        model: Optional[str] = None,
        threshold: float = 0.4,
    ) -> None:
        self._llm = llm
        self._model = model
        self._threshold = threshold

    async def evaluate(
        self,
        step: Step,
        output: str,
        plan: Plan,
        previous_outputs: list[str],
    ) -> StepEvaluation:
        prev_summary = "\n".join(
            f"  [{i+1}] {o[:200]}" for i, o in enumerate(previous_outputs[-3:])
        ) or "  (none)"

        prompt = _EVAL_PROMPT.format(
            plan_goal=plan.title or plan.message or "",
            step_description=step.description,
            output=output[:2000],
            previous_outputs=prev_summary,
        )
        try:
            resp = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._model,
                temperature=TEMPERATURE_DETERMINISTIC,
            )
            data = json.loads(resp.content or "{}")
            score = float(data.get("score", 1.0))
            regression = bool(data.get("regression_detected", False))
            return StepEvaluation(
                step_id=step.id,
                score=score,
                passed=score >= self._threshold and not regression,
                regression_detected=regression,
                reasoning=data.get("reasoning", ""),
                recommendations=data.get("recommendations", []),
            )
        except Exception as exc:
            logger.warning(
                "StepEvaluator LLM call failed: %s — passing step (fail-open)", exc
            )
            return StepEvaluation(
                step_id=step.id,
                score=1.0,
                passed=True,
                regression_detected=False,
                reasoning=f"evaluation failed: {exc}",
            )
