"""EvaluatorSelector — compares evaluators at epoch boundaries (RQGM §3, §4.1).

At each epoch boundary, the selector compares the incumbent evaluator against
challenger evaluators on a ground-truth anchor dataset.  If a challenger
statistically outperforms the incumbent (via epsilon-best-belief score),
the challenger is promoted and selective erasure is applied.

This is the core mechanism enabling controlled utility evolution: within an
epoch, the evaluator is frozen (stationary utility).  At epoch boundaries,
the utility can change (evolved objective).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.evaluator_state import EvaluatorReplacement, EvaluatorState

logger = logging.getLogger(__name__)


class EvaluatorSelector:
    """Compares evaluators at epoch boundaries and promotes challengers.

    Usage::

        selector = EvaluatorSelector(
            llm=container.get(LLMPort),
            anchor_path="weebot/config/harness/evaluator_anchor.yaml",
        )
        promoted = await selector.compare_and_replace(
            incumbent=current_evaluator,
            challenger=candidate_evaluator,
            epoch=3,
        )
        if promoted:
            # Apply selective erasure
            ...
    """

    def __init__(
        self,
        llm: LLMPort,
        anchor_path: str | Path = "weebot/config/harness/evaluator_anchor.yaml",
        epsilon: float = 0.05,
    ) -> None:
        self._llm = llm
        self._anchor_path = Path(anchor_path)
        self._epsilon = epsilon

        # Load anchor dataset
        if self._anchor_path.exists():
            with open(self._anchor_path) as f:
                data = yaml.safe_load(f)
            self._anchor_tasks = data.get("tasks", [])
        else:
            logger.warning("Evaluator anchor not found at %s — using empty anchor", anchor_path)
            self._anchor_tasks = []

    @property
    def anchor_size(self) -> int:
        return len(self._anchor_tasks)

    async def score_evaluator(self, evaluator: EvaluatorState) -> EvaluatorState:
        """Evaluate *evaluator* against the anchor dataset, updating ``anchor_accuracy``.

        Runs the evaluator's prompt on each anchor task and compares
        the score against the ground-truth score.  Returns a copy with
        updated ``anchor_accuracy`` and ``anchor_total``.
        """
        if not self._anchor_tasks:
            return evaluator

        # Handle cases where evaluator has no prompt (e.g., benchmark/verifier)
        eval_prompt = evaluator.prompt or "Score the output from 0.0 to 1.0."

        total_error = 0.0
        for task in self._anchor_tasks:
            try:
                response = await self._llm.chat(
                    messages=[
                        {"role": "system", "content": eval_prompt},
                        {"role": "user", "content": task["prompt"]},
                    ],
                    temperature=0.0,
                    max_tokens=100,
                )
                if response and response.content:
                    import re
                    match = re.search(r"(\d+\.?\d*)", response.content)
                    if match:
                        predicted = float(match.group(1))
                        # Handle both 0-1 and 1-10 scales
                        if predicted > 1.0:
                            predicted /= 10.0
                    else:
                        predicted = 0.5
                else:
                    predicted = 0.5
            except Exception:
                predicted = 0.5

            predicted = max(0.0, min(1.0, predicted))
            ground_truth = task.get("ground_truth_score", 0.5)
            total_error += abs(predicted - ground_truth)

        avg_error = total_error / len(self._anchor_tasks) if self._anchor_tasks else 0.0
        accuracy = 1.0 - avg_error

        return evaluator.model_copy(update={
            "anchor_accuracy": accuracy,
            "anchor_total": len(self._anchor_tasks),
        })

    async def compare_and_replace(
        self,
        incumbent: EvaluatorState,
        challenger: EvaluatorState,
        epoch: int,
    ) -> tuple[bool, EvaluatorState, Optional[str]]:
        """Compare *incumbent* vs *challenger* on the anchor dataset.

        If the challenger statistically outperforms, returns
        ``(True, challenger, reason)``.  Otherwise returns
        ``(False, incumbent, reason)``.

        If either has stale anchor scores (``anchor_total == 0``),
        they are re-scored first.
        """
        reason = ""

        # Score if needed
        if incumbent.anchor_total == 0:
            logger.info("EvaluatorSelector: scoring incumbent %s", incumbent.evaluator_id)
            incumbent = await self.score_evaluator(incumbent)

        if challenger.anchor_total == 0:
            logger.info("EvaluatorSelector: scoring challenger %s", challenger.evaluator_id)
            challenger = await self.score_evaluator(challenger)

        # Compare
        if challenger.statistically_outperforms(incumbent, epsilon=self._epsilon):
            replacement = EvaluatorReplacement(
                epoch=epoch,
                old_evaluator_id=incumbent.evaluator_id,
                new_evaluator_id=challenger.evaluator_id,
                old_anchor_accuracy=incumbent.anchor_accuracy,
                new_anchor_accuracy=challenger.anchor_accuracy,
                reason="Challenger statistically outperforms incumbent on anchor",
            )
            challenger = challenger.model_copy(update={
                "replacement_history": incumbent.replacement_history + [replacement],
            })
            reason = (
                f"Promoted {challenger.evaluator_id} over {incumbent.evaluator_id}: "
                f"accuracy {incumbent.anchor_accuracy:.3f} → {challenger.anchor_accuracy:.3f}"
            )
            logger.info("EvaluatorSelector: %s", reason)
            return True, challenger, reason

        reason = (
            f"Keeping {incumbent.evaluator_id}: "
            f"accuracy {incumbent.anchor_accuracy:.3f} vs "
            f"challenger {challenger.evaluator_id} @ {challenger.anchor_accuracy:.3f}"
        )
        logger.info("EvaluatorSelector: %s", reason)
        return False, incumbent, reason
