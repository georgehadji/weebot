"""PlanTemplateCache — task signature computation + template matching.

When a plan completes successfully, it's saved as a template keyed by
the normalized task description hash. On new task requests, the cache
is queried for matching templates to seed the planner.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Optional

from weebot.domain.models.plan_template import PlanTemplate

logger = logging.getLogger(__name__)

_STOPWORDS: frozenset = frozenset({
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "with",
    "and", "or", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "can", "could", "shall", "should", "may", "might", "must",
    "this", "that", "these", "those", "it", "its", "you", "your",
    "i", "we", "they", "he", "she", "not", "no", "nor", "but",
    "if", "then", "else", "when", "where", "why", "how", "all",
    "each", "every", "both", "few", "more", "most", "some", "any",
    "use", "using", "used", "set", "get", "make", "need", "take",
    "please", "help", "want", "need", "would", "could",
})

_MAX_TASK_CHARS = 2000


def compute_task_hash(task_description: str) -> str:
    """Compute a stable hash for a task description.

    Normalises whitespace, lowercases, and removes stopwords before
    hashing so that minor wording differences don't produce different hashes.
    """
    cleaned = re.sub(r"[^a-z0-9\s]", "", task_description.lower())
    tokens = [t for t in cleaned.split() if t not in _STOPWORDS and len(t) > 2]
    normalised = " ".join(tokens)
    return hashlib.sha256(normalised.encode()).hexdigest()[:16]


def tokenize(text: str) -> set[str]:
    """Tokenize text into a set of significant words for similarity matching."""
    cleaned = re.sub(r"[^a-z0-9\s]", "", text.lower())
    return {t for t in cleaned.split() if t not in _STOPWORDS and len(t) > 2}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


async def find_matching_templates(
    repo: Any,
    task_description: str,
    threshold: float = 0.4,
    max_results: int = 3,
) -> list[PlanTemplate]:
    """Find plan templates matching a task description.

    First tries exact hash match, then falls back to Jaccard similarity
    on all templates (up to ``max_results``).

    Args:
        repo: Repository with ``find_plan_templates_by_hash()`` and
              ``list_all_plan_templates()`` methods.
        task_description: The task description to match.
        threshold: Minimum Jaccard similarity (0.0-1.0). Default 0.4.
        max_results: Maximum number of templates to return.

    Returns:
        List of matching PlanTemplate objects, best match first.
    """
    task_hash = compute_task_hash(task_description)

    # Exact hash match (fast path)
    exact = await repo.find_plan_templates_by_hash(task_hash, limit=max_results)
    if exact:
        return exact

    # Jaccard similarity fallback (slower)
    query_tokens = tokenize(task_description)
    all_templates = await repo.list_all_plan_templates(limit=200)
    scored: list[tuple[float, PlanTemplate]] = []

    for tpl in all_templates:
        sim = jaccard_similarity(query_tokens, tokenize(tpl.task_description))
        if sim >= threshold:
            scored.append((sim, tpl))

    scored.sort(key=lambda x: (-x[0], -x[1].success_score))
    return [t for _, t in scored[:max_results]]


def build_meta_notes(templates: list[PlanTemplate]) -> str:
    """Build a meta_notes string from matching templates to seed the planner.

    Returns an empty string if no templates matched.
    """
    if not templates:
        return ""

    lines = ["[Plan templates from similar tasks]", ""]
    for i, tpl in enumerate(templates[:3], 1):
        try:
            plan_data = json.loads(tpl.plan_json)
            steps = plan_data.get("steps", []) if isinstance(plan_data, dict) else []
            step_lines = [f"  - {s.get('description', '?')}" for s in steps[:8]]
            lines.append(f"Template {i}: {tpl.task_description[:100]}")
            lines.append(f"  Steps ({len(steps)}):")
            lines.extend(step_lines)
            lines.append("")
        except (json.JSONDecodeError, TypeError):
            continue

    return "\n".join(lines) if len(lines) > 2 else ""
