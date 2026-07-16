"""CodeQualitySignal — cheap surrogate evaluation for the RegressionGate.

A single-turn LLM call that scores an agent's task output on three
dimensions: artifact presence, verification evidence, and structure
quality.  This is ~1/10th the cost of a full PlanActFlow run and serves
as a fast-reject gate in the RegressionGate: candidates with very low
code quality scores are rejected without running the expensive held-out
evaluation.

From RQGM §5.1: adding a cheap learned evaluator signal saved 1.35×-1.72×
search tokens by guiding the search toward quality without full re-execution.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from weebot.application.ports.llm_port import LLMPort

logger = logging.getLogger(__name__)

_CODE_QUALITY_PROMPT = """You are scoring an agent's task output for quality.
Evaluate the following output on three dimensions:

1. **Artifact presence** — does the output contain the required file, result,
   or answer artifact?  (0.0 = missing, 1.0 = fully present and correct)
2. **Verification evidence** — does the agent appear to have checked its own
   work before concluding?  (0.0 = no verification, 1.0 = thorough verification)
3. **Structure quality** — is the output well-structured, parseable, and
   professionally presented?  (0.0 = unusable, 1.0 = production-quality)

Output ONLY a JSON object with no commentary:
{{ "artifact_presence": 0.0-1.0, "verification_evidence": 0.0-1.0, "structure_quality": 0.0-1.0 }}

Task prompt:
{task_prompt}

Agent output:
{agent_output}
"""


class CodeQualitySignal:
    """Cheap surrogate evaluator for task output quality.

    Uses a single-turn LLM call to score the agent's output, providing
    a fast signal without re-executing the task.  Designed to be used
    as a pre-filter in the RegressionGate before running the expensive
    held-out evaluation.
    """

    def __init__(self, llm: LLMPort, threshold: float = 0.3) -> None:
        self._llm = llm
        self._threshold = threshold

    async def score(
        self,
        task_prompt: str,
        agent_output: str,
    ) -> dict[str, float]:
        """Score a single task's output on three quality dimensions.

        Args:
            task_prompt: The original task prompt sent to the agent.
            agent_output: The agent's output (code, text, etc.).

        Returns:
            Dict with keys ``artifact_presence``, ``verification_evidence``,
            ``structure_quality`` (each 0.0–1.0), and ``composite`` (mean).
        """
        try:
            response = await self._llm.chat(
                messages=[{
                    "role": "user",
                    "content": _CODE_QUALITY_PROMPT.format(
                        task_prompt=task_prompt[:2000],
                        agent_output=agent_output[:3000],
                    ),
                }],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=200,
            )

            if not response or not response.content:
                logger.debug("CodeQualitySignal: empty response, using defaults")
                return self._default()

            raw = response.content.strip()
            parsed = json.loads(raw)

            return {
                "artifact_presence": max(0.0, min(1.0, float(parsed.get("artifact_presence", 0.0)))),
                "verification_evidence": max(0.0, min(1.0, float(parsed.get("verification_evidence", 0.0)))),
                "structure_quality": max(0.0, min(1.0, float(parsed.get("structure_quality", 0.0)))),
                "composite": 0.0,  # computed below
            }

        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.debug("CodeQualitySignal: parse error (%s), using defaults", exc)
            return self._default()

    def composite(self, scores: dict[str, float]) -> float:
        """Compute the overall quality composite (mean of three dimensions)."""
        return (
            scores.get("artifact_presence", 0.0)
            + scores.get("verification_evidence", 0.0)
            + scores.get("structure_quality", 0.0)
        ) / 3.0

    async def fast_reject(
        self,
        task_prompt: str,
        agent_output: str,
    ) -> bool:
        """Return True if this output should be rejected without full evaluation.

        A rejection means the output's composite score is below the threshold
        (default 0.3), indicating very poor quality.  The caller can skip the
        expensive held-out evaluation for this candidate.
        """
        scores = await self.score(task_prompt, agent_output)
        composite = self.composite(scores)
        if composite < self._threshold:
            logger.debug(
                "CodeQualitySignal: fast-reject (composite=%.3f < threshold=%.2f)",
                composite, self._threshold,
            )
            return True
        return False

    @staticmethod
    def _default() -> dict[str, float]:
        """Return default scores when the LLM call fails."""
        return {
            "artifact_presence": 0.5,
            "verification_evidence": 0.5,
            "structure_quality": 0.5,
            "composite": 0.5,
        }
