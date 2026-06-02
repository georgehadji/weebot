"""TrajectoryMonitor — post-execution degenerate pattern detection (Tier 1.3).

Maintains a rolling window of recent tool calls, output hashes, and step
outcomes.  Called after each step in ExecutingState.  When a degenerate
pattern is detected, produces a TrajectoryDiagnosis with a recovery message
for the LLM.

Maps to LIFE-HARNESS "Trajectory Regulation Layer" (Section 4.3.4).
"""
from __future__ import annotations

import hashlib
import logging
from collections import deque
from typing import Optional

from weebot.domain.models.trajectory import TrajectoryDiagnosis, TrajectoryHealth

logger = logging.getLogger(__name__)


class TrajectoryMonitor:
    """Monitor post-execution trajectory for degenerate patterns.

    Args:
        repetition_threshold: Consecutive identical tool calls before flagging.
        stagnation_window: Steps without result change before flagging.
        budget_hotspot_ratio: Fraction of budget a single step can consume.
        exhaustion_ratio: Budget consumed before flagging exhaustion.
    """

    def __init__(
        self,
        repetition_threshold: int = 4,
        stagnation_window: int = 3,
        budget_hotspot_ratio: float = 0.4,
        exhaustion_ratio: float = 0.9,
    ) -> None:
        self._repetition_threshold = repetition_threshold
        self._stagnation_window = stagnation_window
        self._budget_hotspot_ratio = budget_hotspot_ratio
        self._exhaustion_ratio = exhaustion_ratio

        # Rolling window across a single plan step
        self._tool_signatures: deque[str] = deque(maxlen=repetition_threshold + 2)
        self._output_hashes: deque[str] = deque(maxlen=stagnation_window + 2)
        self._step_results: deque[str] = deque(maxlen=stagnation_window + 2)

    def diagnose(
        self,
        step_id: str,
        tool_signature: Optional[str] = None,
        tool_output: Optional[str] = None,
        step_result: Optional[str] = None,
        total_budget: int = 0,
        used_budget: int = 0,
    ) -> TrajectoryDiagnosis:
        """Analyze the current trajectory and return a diagnosis.

        Args:
            step_id: Current step identifier.
            tool_signature: Most recent tool call signature.
            tool_output: Most recent tool output (for semantic-loop detection).
            step_result: Most recent step result text.
            total_budget: Total step budget for this executor run.
            used_budget: Steps consumed so far.

        Returns:
            TrajectoryDiagnosis — HEALTHY if no issue, otherwise with
            a recovery_message suitable for injection into the LLM context.
        """
        if tool_signature:
            self._tool_signatures.append(tool_signature)
        if tool_output:
            h = hashlib.md5(tool_output.encode()).hexdigest()
            self._output_hashes.append(h)
        if step_result:
            self._step_results.append(step_result)

        # 1. Exact repetition — same tool call repeatedly
        if len(self._tool_signatures) >= self._repetition_threshold:
            recent = list(self._tool_signatures)[-self._repetition_threshold:]
            if len(set(recent)) == 1:
                return TrajectoryDiagnosis(
                    health=TrajectoryHealth.REPEATING,
                    detail=f"Tool {recent[0]!r} called {self._repetition_threshold}x consecutively",
                    recovery_message=(
                        f"You have called {recent[0]!r} {self._repetition_threshold}x in a row "
                        "with no change. Stop and try a different approach."
                    ),
                    affected_step_ids=[step_id],
                )

        # 2. Semantic loop — different calls but same output
        if len(self._output_hashes) >= self._stagnation_window:
            recent = list(self._output_hashes)[-self._stagnation_window:]
            if len(set(recent)) <= 1:
                return TrajectoryDiagnosis(
                    health=TrajectoryHealth.SEMANTIC_LOOP,
                    detail="Different tool calls producing identical output",
                    recovery_message=(
                        "Your recent tool calls are producing the same output. "
                        "You are in a semantic loop. Stop and try a completely different search strategy."
                    ),
                    affected_step_ids=[step_id],
                )

        # 3. Stagnation — step result unchanged across steps
        if len(self._step_results) >= self._stagnation_window:
            recent = list(self._step_results)[-self._stagnation_window:]
            if len(set(recent)) <= 1:
                return TrajectoryDiagnosis(
                    health=TrajectoryHealth.STAGNATING,
                    detail="Step result unchanged across multiple steps",
                    recovery_message=(
                        f"No progress detected in the last {self._stagnation_window} steps. "
                        "Re-read the task and take a fundamentally different approach."
                    ),
                    affected_step_ids=[step_id],
                )

        # 4. Budget hotspot — one step consuming disproportionate budget
        if total_budget > 0 and used_budget > 0:
            usage_ratio = used_budget / total_budget
            if usage_ratio >= self._exhaustion_ratio:
                return TrajectoryDiagnosis(
                    health=TrajectoryHealth.EXHAUSTED,
                    detail=f"Step budget at {usage_ratio:.0%} with no completion",
                    recovery_message=(
                        f"You have used {usage_ratio:.0%} of your step budget "
                        f"({used_budget}/{total_budget}). Focus on completing the current "
                        "step or summarize what you have."
                    ),
                    affected_step_ids=[step_id],
                )

        return TrajectoryDiagnosis(health=TrajectoryHealth.HEALTHY)
