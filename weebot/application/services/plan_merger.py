"""Plan merger — evaluates and merges multiple PlanCandidate objects into a final Plan.

Companion module to ``parallel_planner.py`` (DPPM).  After generating
candidate plans, the merger evaluates their consistency with the original
task and assembles the best combination of subtask alternatives.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from weebot.application.agents.parallel_planner import PlanCandidate
from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.plan import Plan, Step, StepStatus, PlanStatus

logger = logging.getLogger(__name__)


class PlanMerger:
    """Evaluates and merges DPPM plan candidates into a final Plan.

    Usage:
        merger = PlanMerger(llm=llm_port)
        final_plan = await merger.merge(candidates, prompt)
    """

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def merge(
        self,
        candidates: list[PlanCandidate],
        original_prompt: str,
    ) -> Optional[Plan]:
        """Select and refine the best plan candidate.

        Strategy:
        1. Score candidates by an LLM call.
        2. Pick the highest-scored candidate.
        3. Optionally refine step descriptions for consistency.

        Args:
            candidates: List of PlanCandidate from ParallelPlanner.
            original_prompt: The original user task prompt.

        Returns:
            Final Plan object, or None if all candidates fail.
        """
        if not candidates:
            return None

        if len(candidates) == 1:
            return candidates[0].to_plan()

        # LLM call to select and rank candidates
        best_candidate = await self._select_best(candidates, original_prompt)
        if best_candidate is None:
            # Fallback: pick the first candidate
            best_candidate = candidates[0]

        plan = best_candidate.to_plan()
        logger.info(
            "DPPM merger: selected plan with %d steps (score=%.2f)",
            len(plan.steps), best_candidate.score,
        )
        return plan

    async def _select_best(
        self,
        candidates: list[PlanCandidate],
        original_prompt: str,
    ) -> Optional[PlanCandidate]:
        """LLM call: evaluate and rank plan candidates."""
        candidates_text = ""
        for i, c in enumerate(candidates):
            steps_text = "\n".join(
                f"    {s.id}. {s.description}" for s in c.steps
            )
            candidates_text += (
                f"Candidate {i + 1} (score={c.score:.2f}):\n{steps_text}\n\n"
            )

        sys_prompt = (
            "You are a plan evaluation expert. Given a task and multiple plan "
            "candidates, select the best one.\n\n"
            f"Task: {original_prompt}\n\n"
            f"Candidates:\n{candidates_text}\n\n"
            "Respond with JSON: {\"best\": 1, \"reason\": \"one-sentence explanation\"}\n"
            "\"best\" is the 1-based index of the candidate you select."
        )
        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": sys_prompt}],
                max_tokens=200,
            )
            text = response.content.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)
            best_idx = int(data.get("best", 1)) - 1
            if 0 <= best_idx < len(candidates):
                selected = candidates[best_idx]
                logger.info("DPPM merger selected candidate %d: %s", best_idx + 1, data.get("reason", ""))
                return selected
        except Exception as exc:
            logger.warning("DPPM candidate selection failed: %s", exc)

        return None
