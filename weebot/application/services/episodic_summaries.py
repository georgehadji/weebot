"""Episodic summaries: what worked on a similar task, as notes for the planner.

CompletedState saves a short summary of each fully successful plan; PlanningState
turns the closest past summaries into notes. Both sides are best-effort: a
summary that cannot be saved or read never blocks a run.
"""

from __future__ import annotations

import logging
from typing import Any

from weebot.domain.models.plan import Plan, StepStatus

logger = logging.getLogger(__name__)

# Below this a past task is about something else (cosine or token Jaccard).
_MIN_SIMILARITY = 0.3


def summarise_plan(plan: Plan | None) -> str | None:
    """A few lines on what a plan did; None unless every step completed."""
    if plan is None or not plan.steps:
        return None
    if any(s.status != StepStatus.COMPLETED for s in plan.steps):
        return None
    steps = "; ".join(s.description[:80] for s in plan.steps)
    last = (plan.steps[-1].result or "").strip()
    text = f"{plan.title or 'Plan'}: {steps}"
    if last:
        text += f". Outcome: {last[:200]}"
    return text[:600]


async def save_session_summary(repo: Any | None, session_id: str, task: str, plan: Plan) -> None:
    """Save the plan's summary under *task*; a failure is logged, never raised."""
    summary = summarise_plan(plan)
    if repo is None or not task or summary is None:
        return
    try:
        await repo.save_summary(session_id, task[:500], summary)
    except Exception:
        logger.warning("Episodic summary save failed for %s", session_id[:8], exc_info=True)


async def similar_session_notes(repo: Any | None, task: str, limit: int = 2) -> list[str]:
    """Up to *limit* notes from past successes on a similar task; [] on any problem."""
    if repo is None or not task:
        return []
    try:
        matches = await repo.find_similar(task, k=limit)
    except Exception as exc:
        logger.debug("Episodic summary lookup skipped: %s", exc)
        return []
    return [
        f"A similar past task succeeded ('{past[:80]}'): {summary[:240]}"
        for _sid, past, summary, score in matches
        if score >= _MIN_SIMILARITY
    ]
