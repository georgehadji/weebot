"""Trajectory builder — converts a completed Session into a TrajectorySummary.

Uses a fast, cheap LLM call to condense the event stream into a compact
natural-language trajectory text and to classify failure/success patterns.
"""
from __future__ import annotations

import logging
from typing import Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.event import TrajectoryScored
from weebot.domain.models.session import Session
from weebot.domain.models.trajectory import TrajectorySummary

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """You are a trajectory analyst. Given a list of events from an agent session,
produce a compact natural-language summary of what happened and classify
failure/success patterns.

Respond ONLY with valid JSON:
{
    "trajectory_text": "concise natural-language summary of the agent's actions (1-3 sentences)",
    "failure_modes": ["list", "of", "failure", "categories"],
    "success_patterns": ["list", "of", "success", "categories"]
}

Rules:
- trajectory_text should be 50-200 tokens.
- failure_modes: empty list if the task succeeded fully.
- success_patterns: empty list if the task failed fully.
- Be specific: 'wrong_tool_choice' not 'error', 'correct_formatting' not 'good'.
"""


class TrajectoryBuilder:
    """Builds TrajectorySummary from a completed session.

    Uses a lightweight LLM call to classify failure/success patterns
    and generate a compact trajectory text.  The trajectory text is
    what the optimizer model sees during reflection.
    """

    def __init__(self, llm: LLMPort):
        self._llm = llm

    async def build(
        self,
        session: Session,
        scored_event: TrajectoryScored,
    ) -> TrajectorySummary:
        """Build a TrajectorySummary from a completed session.

        Args:
            session: The completed session with full event history.
            scored_event: The TrajectoryScored event with score data.

        Returns:
            A TrajectorySummary ready for persistence.
        """
        # Build a compact event stream for the analyst LLM
        event_digest = self._digest_events(session)

        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": ANALYSIS_PROMPT},
                    {"role": "user", "content": event_digest},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=500,
            )
            analysis = __import__("json").loads(response.content)
        except Exception as exc:
            logger.warning("Trajectory analysis LLM call failed: %s", exc)
            analysis = {
                "trajectory_text": scored_event.trajectory_summary,
                "failure_modes": [],
                "success_patterns": [],
            }

        # Extract skill info from session context
        skill_name = session.context.get("skill_name", "")
        skill_version = session.context.get("skill_version", 0)

        # Calculate tool calls and tokens from events
        tool_call_count = 0
        total_tokens = 0
        total_cost = 0.0
        for e in session.events:
            if e.type == "tool":
                tool_call_count += 1

        return TrajectorySummary(
            task_id=scored_event.task_id,
            session_id=session.id,
            skill_name=skill_name,
            skill_version=skill_version,
            harness=scored_event.harness,
            score=scored_event.score,
            passed=scored_event.score >= 0.5,
            failure_modes=analysis.get("failure_modes", []),
            success_patterns=analysis.get("success_patterns", []),
            tool_call_count=tool_call_count,
            total_tokens=total_tokens,
            total_cost=total_cost,
            trajectory_text=analysis.get("trajectory_text", scored_event.trajectory_summary),
            answer=None,
            expected_answer=None,
        )

    @staticmethod
    def _digest_events(session: Session) -> str:
        """Produce a compact string of the session's event types and content."""
        lines = [f"Session: {session.id}", f"Status: {session.status.value}", ""]
        for e in session.events:
            if e.type == "message":
                lines.append(f"[{e.type}] {e.role}: {(e.message or '')[:200]}")
            elif e.type == "tool":
                lines.append(
                    f"[{e.type}] {getattr(e, 'tool_name', '')}: "
                    f"{(str(getattr(e, 'result', '')) or '')[:200]}"
                )
            elif e.type == "step":
                lines.append(
                    f"[{e.type}] {getattr(e, 'step_id', '')}: "
                    f"{getattr(e, 'status', '')}"
                )
            elif e.type == "error":
                lines.append(f"[{e.type}] {(getattr(e, 'error', ''))[:200]}")
            else:
                lines.append(f"[{e.type}]")
        return "\n".join(lines)

    @staticmethod
    def from_events(
        session: Session,
        scored_event: TrajectoryScored,
        analysis: dict,
    ) -> TrajectorySummary:
        """Build a TrajectorySummary from already-analysed data (no LLM call).

        Used when the caller already has the analysis (e.g., from a
        known-answer scoring run).
        """
        tool_call_count = sum(1 for e in session.events if e.type == "tool")
        skill_name = session.context.get("skill_name", "")
        skill_version = session.context.get("skill_version", 0)

        return TrajectorySummary(
            task_id=scored_event.task_id,
            session_id=session.id,
            skill_name=skill_name,
            skill_version=skill_version,
            harness=scored_event.harness,
            score=scored_event.score,
            passed=scored_event.score >= 0.5,
            failure_modes=analysis.get("failure_modes", []),
            success_patterns=analysis.get("success_patterns", []),
            tool_call_count=tool_call_count,
            total_tokens=0,
            total_cost=0.0,
            trajectory_text=analysis.get("trajectory_text", scored_event.trajectory_summary),
            answer=None,
            expected_answer=None,
        )
