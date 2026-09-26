"""PlanOutcomeScorer — scores a live session by what its own plan recorded.

The three other scorers in this package are benchmark scorers: each compares
the agent's answer against an EXPECTED answer. A live user session has none.
Wired to live sessions, ``ExactMatchScorer`` scores every one 0.0,
``ExecutionResultScorer`` returns a flat 0.5 flagged ``no_expected_output``,
and ``VerifierScorer`` pays for an LLM call to compare against nothing -- a
constant, meaningless score fed into the data the self-learning loop learns
from.

A live session does carry one honest outcome signal: its plan. Steps are
marked COMPLETED, FAILED or UNVERIFIED (executed, but the evidence did not
support completion) as they run. This scores the fraction that COMPLETED,
which is exactly the rule ``Plan.is_successful()`` applies -- so a plan in
which every step failed scores 0.0 here, not the 1.0 that ``is_complete()``
would have implied.

No LLM call. Deterministic, so the same session always scores the same.
"""

from __future__ import annotations

from weebot.application.ports.scoring_port import ScoringPort
from weebot.domain.models.event import TrajectoryScored
from weebot.domain.models.plan import StepStatus
from weebot.domain.models.session import Session

HARNESS = "plan_outcome"


class PlanOutcomeScorer(ScoringPort):
    """Score = fraction of the plan's steps that COMPLETED."""

    async def score(self, session: Session, expected_answer: str | None = None) -> TrajectoryScored:
        plan = session.get_last_plan()

        if plan is None or not plan.steps:
            # Nothing was planned, so nothing was achieved. Scored 0.0 and
            # named, not skipped: a flow that could not plan is a failure the
            # learning loop should see.
            return TrajectoryScored(
                session_id=session.id,
                task_id=session.id,
                score=0.0,
                failure_modes=["no_plan"],
                success_patterns=[],
                trajectory_summary="The session produced no plan.",
                harness=HARNESS,
            )

        total = len(plan.steps)
        completed = [s for s in plan.steps if s.status == StepStatus.COMPLETED]
        failure_modes: list[str] = []
        for step in plan.steps:
            if step.status == StepStatus.FAILED:
                failure_modes.append(f"step_failed: {step.description[:80]}")
            elif step.status == StepStatus.UNVERIFIED:
                failure_modes.append(f"step_unverified: {step.description[:80]}")
            elif step.status != StepStatus.COMPLETED:
                failure_modes.append(f"step_not_finished: {step.description[:80]}")

        succeeded = plan.is_successful()
        return TrajectoryScored(
            session_id=session.id,
            task_id=session.id,
            score=len(completed) / total,
            failure_modes=failure_modes,
            success_patterns=["plan_succeeded"] if succeeded else [],
            trajectory_summary=f"{len(completed)} of {total} plan steps completed.",
            harness=HARNESS,
        )
