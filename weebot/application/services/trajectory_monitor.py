"""TrajectoryMonitor — post-execution degenerate pattern detection (Tier 1.3).

Maintains a rolling window of recent tool calls, output hashes, and step
outcomes.  Called after each step in ExecutingState.  When a degenerate
pattern is detected, produces a TrajectoryDiagnosis with a recovery message
for the LLM.

Maps to LIFE-HARNESS "Trajectory Regulation Layer" (Section 4.3.4).

Phase 6 enhancement: cross-step trajectory tracking.  ``reset_step()``
clears per-step rolling windows while preserving cross-step accumulators,
so the monitor can detect multi-step degenerate patterns (e.g. 3+
consecutive error-producing steps).
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
        cross_step_failure_threshold: Consecutive error-producing steps before flagging.
    """

    def __init__(
        self,
        repetition_threshold: int = 4,
        stagnation_window: int = 3,
        budget_hotspot_ratio: float = 0.4,
        exhaustion_ratio: float = 0.9,
        cross_step_failure_threshold: int = 3,
    ) -> None:
        self._repetition_threshold = repetition_threshold
        self._stagnation_window = stagnation_window
        self._budget_hotspot_ratio = budget_hotspot_ratio
        self._exhaustion_ratio = exhaustion_ratio
        self._cross_step_failure_threshold = cross_step_failure_threshold

        # Rolling window across a single plan step
        self._tool_signatures: deque[str] = deque(maxlen=repetition_threshold + 2)
        self._output_hashes: deque[str] = deque(maxlen=stagnation_window + 2)
        self._step_results: deque[str] = deque(maxlen=stagnation_window + 2)

        # Phase 6: Cross-step accumulators (preserved across reset_step())
        self._consecutive_failed_steps: int = 0
        self._cross_step_error_outputs: deque[str] = deque(maxlen=5)

    def reset_step(self) -> None:
        """Clear per-step rolling windows; preserve cross-step accumulators.

        Call at the beginning of each new plan step so that per-step
        detectors (repetition, semantic loop) start fresh while the
        cross-step failure counter accumulates across the full session.
        """
        self._tool_signatures.clear()
        self._output_hashes.clear()
        # NOTE: _step_results is cross-step by design — do NOT clear it here.
        # _consecutive_failed_steps and _cross_step_error_outputs are also
        # cross-step — preserved.

    def diagnose(
        self,
        step_id: str,
        tool_signature: Optional[str] = None,
        tool_output: Optional[str] = None,
        step_result: Optional[str] = None,
        total_budget: int = 0,
        used_budget: int = 0,
        available_tools: Optional[list[str]] = None,
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
        if tool_output is not None:
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
                tool_hint = ""
                if available_tools:
                    tool_hint = (
                        " Available tools you can switch to: "
                        + ", ".join(available_tools[:6])
                        + ". Use web_search for any internet research — never bash curl/wget."
                    )
                return TrajectoryDiagnosis(
                    health=TrajectoryHealth.SEMANTIC_LOOP,
                    detail="Different tool calls producing identical output",
                    recovery_message=(
                        "SEMANTIC LOOP DETECTED: Your last tool calls produced identical output. "
                        "Do NOT retry the same tool. Switch to a completely different tool and approach."
                        + tool_hint
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

        # 5. Terminal — all recent tool calls are producing errors
        # (models or external services may be unavailable).
        # Only trigger when the recent output hashes are ALL from
        # error outputs — different healthy outputs should NOT trigger
        # this detector.  Previously used tool *signature* diversity
        # which flagged normal multi-tool exploration as terminal.
        if used_budget > 5 and len(self._output_hashes) >= 4:
            recent_outputs = list(self._output_hashes)[-4:]
            recent_sigs = list(self._tool_signatures)[-4:]
            # Only flag when ALL recent outputs are identical (errors
            # produce similar/nil output) AND the signatures are all
            # different (model is frantically trying different things).
            outputs_stuck = len(set(recent_outputs)) <= 1
            sigs_different = len(set(recent_sigs)) >= 3
            if outputs_stuck and sigs_different:
                return TrajectoryDiagnosis(
                    health=TrajectoryHealth.TERMINAL,
                    detail="All recent tool calls have produced identical (error) "
                           "output despite different approaches — models or "
                           "external services may be unavailable",
                    recovery_message=None,
                    affected_step_ids=[step_id],
                )

        # 6. Phase 6: Cross-step failure accumulation — 3+ consecutive
        #    error-producing steps indicate a systemic failure.
        if tool_output and "ERROR" in tool_output.upper():
            self._cross_step_error_outputs.append(tool_output[:100])
            self._consecutive_failed_steps += 1
        else:
            self._consecutive_failed_steps = 0

        if self._consecutive_failed_steps >= self._cross_step_failure_threshold:
            return TrajectoryDiagnosis(
                health=TrajectoryHealth.TERMINAL,
                detail=(
                    f"{self._cross_step_failure_threshold} consecutive steps "
                    f"produced errors — possible systemic failure"
                ),
                recovery_message=(
                    "Multiple consecutive steps have produced errors. "
                    "This may indicate a systemic problem (API outage, "
                    "missing dependencies, or configuration issue). "
                    "Consider pausing and reassessing rather than retrying."
                ),
                affected_step_ids=[step_id],
            )

        return TrajectoryDiagnosis(health=TrajectoryHealth.HEALTHY)
