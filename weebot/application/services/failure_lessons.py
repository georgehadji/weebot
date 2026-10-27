"""Notes for the planner from past runs that failed on a similar task.

A failed run's trajectory keeps its task and failure modes. Before planning, the
closest failures (Jaccard over the same tokens the plan-template cache matches on)
become short notes, so the planner can avoid repeating them.
"""

from __future__ import annotations

import logging
from typing import Any

from weebot.domain.services.plan_template_cache import jaccard_similarity, tokenize

logger = logging.getLogger(__name__)

# Below this overlap a past failure is about something else.
_MIN_SIMILARITY = 0.3


async def similar_failure_notes(repo: Any | None, task: str, limit: int = 2) -> list[str]:
    """Up to *limit* notes, most similar failure first; [] on any problem."""
    if repo is None or not task:
        return []
    try:
        failures = await repo.recent_failures()
    except Exception as exc:
        logger.debug("Past-failure lookup skipped: %s", exc)
        return []
    wanted = tokenize(task)
    scored = []
    for t in failures:
        score = jaccard_similarity(wanted, tokenize(t.task_text))
        if score >= _MIN_SIMILARITY and (t.failure_modes or t.trajectory_text):
            scored.append((score, t))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    notes = []
    for _, t in scored[:limit]:
        why = "; ".join(t.failure_modes[:3]) or t.trajectory_text[:200]
        notes.append(f"Past failure on a similar task ('{t.task_text[:80]}'): {why}")
    return notes
