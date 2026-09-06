"""Trajectory builder — converts a completed Session into a TrajectorySummary.

Uses a fast, cheap LLM call to condense the event stream into a compact
natural-language trajectory text and to classify failure/success patterns.
"""

from __future__ import annotations

import json
import logging

from weebot.application.ports.llm_port import LLMPort
from weebot.config.constants import MAX_TOKENS_SHORT, TEMPERATURE_PRECISE
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


def _validate_analysis(analysis: object) -> None:
    """Reject a completion that parsed but cannot be used.

    `json.loads` happily returns a list, a string or a number, and the builder
    then calls `.get` on whatever comes back -- so a valid but wrong-shaped
    completion escaped the fail-open entirely and raised out of `build`, past
    the very handler meant to absorb analyst failures. `.get(key, default)`
    does not help: it substitutes the default only when the key is ABSENT, so
    `{"failure_modes": "oops"}` sails through to Pydantic and raises there
    instead.

    Both were found by the RAR invalid-input vector, one after the other -- the
    container type first, then the field types, which is the same defect one
    level down. Checking the whole shape at once is the only version that ends
    the sequence.

    A response that gets any of this wrong is not trustworthy for the fields it
    did get right, so a violation invalidates the whole analysis rather than
    part of it.
    """
    if not isinstance(analysis, dict):
        raise TypeError(f"analyst returned {type(analysis).__name__}, expected a JSON object")
    text = analysis.get("trajectory_text", "")
    if not isinstance(text, str):
        raise TypeError(f"trajectory_text is {type(text).__name__}, expected str")
    for key in ("failure_modes", "success_patterns"):
        value = analysis.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise TypeError(f"{key} is not a list of strings: {value!r}")


class TrajectoryBuilder:
    """Builds TrajectorySummary from a completed session.

    Uses a lightweight LLM call to classify failure/success patterns
    and generate a compact trajectory text.  The trajectory text is
    what the optimizer model sees during reflection.
    """

    def __init__(self, llm: LLMPort):
        self._llm = llm

    async def build(self, session: Session, scored_event: TrajectoryScored) -> TrajectorySummary:
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
                temperature=TEMPERATURE_PRECISE,
                max_tokens=MAX_TOKENS_SHORT,
            )
            analysis = json.loads(response.content)
            _validate_analysis(analysis)
        except Exception as exc:
            logger.warning("Trajectory analysis LLM call failed: %s", exc)
            # NOT an empty list. The analyst prompt above defines
            # "failure_modes: empty list if the task succeeded fully", and this
            # value is persisted and read back by the optimizer -- so `[]` here
            # asserts a clean run for a trajectory nothing ever looked at, and
            # dilutes the dataset with rows that silently claim success. An
            # explicit marker is greppable, survives the round trip through
            # SQLite, and needs no schema change; `verifier_scorer` already uses
            # the field this way with "no_expected_answer".
            analysis = {
                "trajectory_text": scored_event.trajectory_summary,
                "failure_modes": ["analysis_unavailable"],
                "success_patterns": [],
            }

        # Extract skill info from session context
        skill_name = session.context.get("skill_name", "")
        skill_version = session.context.get("skill_version", 0)

        # Calculate tool calls and tokens from events
        tool_call_count = 0
        total_tokens = 0
        total_cost = 0.0
        actions: list[str] = []
        for e in session.events:
            if e.type == "tool":
                tool_call_count += 1
                actions.append(getattr(e, "tool_name", "") or "")

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
            actions=actions,
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
                    f"[{e.type}] {getattr(e, 'step_id', '')}: " f"{getattr(e, 'status', '')}"
                )
            elif e.type == "error":
                lines.append(f"[{e.type}] {(getattr(e, 'error', ''))[:200]}")
            else:
                lines.append(f"[{e.type}]")
        return "\n".join(lines)

    @staticmethod
    def from_events(
        session: Session, scored_event: TrajectoryScored, analysis: dict
    ) -> TrajectorySummary:
        """Build a TrajectorySummary from already-analysed data (no LLM call).

        Used when the caller already has the analysis (e.g., from a
        known-answer scoring run).
        """
        tool_call_count = sum(1 for e in session.events if e.type == "tool")
        actions = [getattr(e, "tool_name", "") or "" for e in session.events if e.type == "tool"]
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
            actions=actions,
        )
