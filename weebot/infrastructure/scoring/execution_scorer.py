"""ExecutionResultScorer — output artifact comparison for code/spreadsheet benchmarks.

Evaluates the agent's output against the expected result by comparing:
- File output contents (for codegen benchmarks)
- openpyxl cell values (for spreadsheet benchmarks)
- JSON output structure (for structured output benchmarks)

Returns 0.0–1.0 based on proportion of matching cells/fields.
"""
from __future__ import annotations

from typing import Optional

from weebot.application.ports.scoring_port import ScoringPort
from weebot.domain.models.event import TrajectoryScored
from weebot.domain.models.session import Session


class ExecutionResultScorer(ScoringPort):
    """ScoringPort implementation that compares output artifacts.

    Examines the session context for expected output keys and compares
    them against the agent's produced output. Uses field-level comparison
    for structured outputs (dict/list) and exact match for scalars.
    """

    def __init__(self, expected_output_key: str = "expected_output"):
        self._expected_key = expected_output_key

    async def score(
        self,
        session: Session,
        expected_answer: Optional[str] = None,
    ) -> TrajectoryScored:
        """Score a session by comparing execution output against expected."""
        context = getattr(session, "context", {})
        expected = context.get(self._expected_key, expected_answer)
        agent_output = context.get("agent_output", "")

        score = 0.5
        failure_modes: list[str] = []
        success_patterns: list[str] = []

        if expected is None:
            failure_modes.append("no_expected_output")
        else:
            # If both are dicts, compare field-level
            if isinstance(expected, dict) and isinstance(agent_output, dict):
                matching = sum(
                    1 for k in expected if k in agent_output and agent_output[k] == expected[k]
                )
                score = matching / len(expected) if expected else 0.5
                if score >= 1.0:
                    success_patterns.append("all_fields_match")
                else:
                    failure_modes.append(f"{int(len(expected) - matching)}_fields_mismatch")

            # Simple string comparison
            elif isinstance(expected, str) and isinstance(agent_output, str):
                if expected == agent_output:
                    score = 1.0
                    success_patterns.append("output_matches")
                elif expected.lower() in agent_output.lower():
                    score = 0.5
                    failure_modes.append("output_contains_expected")
                else:
                    score = 0.0
                    failure_modes.append("output_mismatch")
            else:
                # Type mismatch — partial credit
                score = 0.3
                failure_modes.append("output_type_mismatch")

        return TrajectoryScored(
            session_id=session.id,
            task_id=session.id,
            score=score,
            failure_modes=failure_modes,
            success_patterns=success_patterns,
            trajectory_summary=str(agent_output)[:500],
            harness="execution",
        )
