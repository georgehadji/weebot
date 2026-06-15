"""HarnessMetricScorer — computes HarnessMetrics from a finished Session + evaluation records.

Pure computation over:
- A finished ``Session`` (for trajectory efficiency, recovery ability, state consistency)
- Per-task oracle results (for task_pass_rate)
- Verification/action evidence stored on the session's events (for verification_strength
  — Phase 3 will provide ActionEvidence, currently approximated from VerificationEvents)
- Governance decisions logged during the session (for safety_compliance — Phase 4)

The scorer is stateless and testable — it takes data, returns metrics.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from weebot.domain.models.event import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    ToolEvent,
    VerificationEvent,
)
from weebot.domain.models.harness_metrics import HarnessMetrics
from weebot.domain.models.session import Session

logger = logging.getLogger(__name__)


class HarnessMetricScorer:
    """Computes HarnessMetrics from a finished session and evaluation results."""

    # Configurable defaults — can be overridden per scorer
    DEFAULT_TOOL_TOKEN_COST: float = 0.002  # USD per tool call token (approx)
    DEFAULT_WALL_CLOCK_MAX_SECONDS: float = 300.0  # 5 min = max score

    @classmethod
    def score(
        cls,
        session: Session,
        task_passed: bool = True,
        tool_call_data: Optional[dict] = None,
        wall_clock_seconds: Optional[float] = None,
    ) -> HarnessMetrics:
        """Score a finished session across all six metrics.

        Args:
            session: A finished Session with events.
            task_passed: Whether the overall task passed.
            tool_call_data: Optional dict with ``calls``, ``tokens``, ``cost``.
            wall_clock_seconds: Total wall-clock time for the session.

        Returns:
            HarnessMetrics computed from the available data.
        """
        events = session.events

        # ── Metrics from events ──────────────────────────────────

        # Trajectory efficiency: normalised inverted tool-call density.
        # Fewer tool calls per solved task = more efficient.
        tool_calls = cls._count_tool_calls(events)
        task_pass_rate = 1.0 if task_passed else 0.0
        trajectory_efficiency = cls._efficiency_score(
            tool_calls=tool_calls,
            wall_clock_seconds=wall_clock_seconds,
            task_passed=task_passed,
        )

        # Verification strength: fraction of steps with a verification gate.
        verification_strength = cls._compute_verification_strength(events)

        # Recovery ability: fraction of ErrorEvents followed by successful
        # continuation (not a DoneEvent(FAILED) within N events).
        recovery_ability = cls._compute_recovery_ability(events)

        # Replayability: fraction of events that are fully reconstructable
        # from log data (ToolEvent with result, MessageEvent with message).
        replayability = cls._compute_replayability(events)

        # State consistency: approximated by ratio of persisted events
        # to expected events (all events are persisted in the current
        # implementation, so defaults to 1.0 for sessions that loaded
        # successfully).
        state_consistency = cls._compute_state_consistency(events)

        # Safety compliance: placeholder for Phase 4 governance data.
        # Currently defaults to 1.0 (no governance = no violations).
        safety_compliance = 1.0

        return HarnessMetrics(
            trajectory_efficiency=trajectory_efficiency,
            verification_strength=verification_strength,
            recovery_ability=recovery_ability,
            state_consistency=state_consistency,
            safety_compliance=safety_compliance,
            replayability=replayability,
            task_pass_rate=task_pass_rate,
        )

    # ── Internal helpers ──────────────────────────────────────────

    @classmethod
    def _count_tool_calls(cls, events: list[AgentEvent]) -> int:
        return sum(1 for e in events if isinstance(e, ToolEvent))

    @classmethod
    def _efficiency_score(
        cls,
        tool_calls: int,
        wall_clock_seconds: Optional[float],
        task_passed: bool,
    ) -> float:
        """Normalised trajectory efficiency.

        Ideal: 1 call / completed task in under 30s → score ~0.95.
        Degraded: 50+ calls or timeout → score ~0.1.
        """
        if not task_passed:
            return max(0.0, 1.0 - (tool_calls / 100.0))

        # Tool-call efficiency (fewer = better)
        call_score = max(0.0, 1.0 - (tool_calls / 50.0))

        # Time efficiency (faster = better)
        if wall_clock_seconds is not None and wall_clock_seconds > 0:
            time_score = max(
                0.0,
                1.0 - (wall_clock_seconds / cls.DEFAULT_WALL_CLOCK_MAX_SECONDS),
            )
        else:
            time_score = 0.5  # neutral if no time data

        return 0.6 * call_score + 0.4 * time_score

    @classmethod
    def _compute_verification_strength(cls, events: list[AgentEvent]) -> float:
        """Fraction of steps that have a VerificationEvent nearby.

        Approximated from the existing VerificationEvent type. Phase 3
        will enrich this with ActionEvidence.scope coverage data.
        """
        verify_events = [
            e for e in events if isinstance(e, VerificationEvent)
        ]
        if not events:
            return 0.0
        return min(1.0, len(verify_events) / max(1, len(events) * 0.2))

    @classmethod
    def _compute_recovery_ability(cls, events: list[AgentEvent]) -> float:
        """Fraction of errors that the agent recovered from.

        A recovery is counted when an ErrorEvent is followed by a
        non-Error, non-Done event within 5 positions.
        """
        errors_recovered = 0
        total_errors = 0
        for i, event in enumerate(events):
            if isinstance(event, ErrorEvent):
                total_errors += 1
                # Look ahead 5 events for successful continuation
                lookahead = events[i + 1 : i + 6]
                recovered = any(
                    not isinstance(e, (ErrorEvent, DoneEvent))
                    for e in lookahead
                )
                if recovered:
                    errors_recovered += 1

        if total_errors == 0:
            return 1.0  # no errors = perfect recovery
        return errors_recovered / total_errors

    @classmethod
    def _compute_replayability(cls, events: list[AgentEvent]) -> float:
        """Fraction of events that carry full reconstructable data."""
        if not events:
            return 0.0
        replayable = sum(
            1
            for e in events
            if cls._is_replayable(e)
        )
        return replayable / len(events)

    @classmethod
    def _is_replayable(cls, event: AgentEvent) -> bool:
        """Check if a single event has sufficient data for replay."""
        if isinstance(event, ToolEvent):
            return bool(event.result)
        if hasattr(event, "message") and event.message:
            return True
        return True  # most event types are replayable

    @classmethod
    def _compute_state_consistency(cls, events: list[AgentEvent]) -> float:
        """State consistency score.

        With the current SQLite persistence, all events are persisted
        atomically within each save.  For sessions that loaded
        successfully (which is the precondition for calling score()),
        consistency is assumed to be 1.0.

        This metric becomes meaningful when comparing checkpoint-
        reconstructed sessions against the original.
        """
        if not events:
            return 0.0
        return 1.0
