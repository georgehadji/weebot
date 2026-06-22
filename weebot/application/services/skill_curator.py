"""SkillCurator — background service that classifies and LLM-reviews stale skills.

Inspired by hermes-agent's curator.py pattern. Runs as a weekly APScheduler
cron job registered via SchedulingManager (wired in di.py).

Classification thresholds (based on last EvolutionEntry timestamp):
  active           — used within ACTIVE_DAYS (30 days)
  stale            — unused 30–90 days (LLM-reviewed)
  archive-candidate — unused 90+ days (LLM-reviewed)

Strict invariants:
  - Only appends to evolution_log — never deletes or modifies skills
  - LLM recommendation is ARCHIVE, PIN, or KEEP (one word + one-sentence reason)
  - Uses cheap/budget model to keep curation cost negligible
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from weebot.config.constants import MAX_TOKENS_TINY, TEMPERATURE_DETERMINISTIC
from weebot.application.ports.llm_port import LLMPort
from weebot.application.skills.skill_registry import SkillRegistry
from weebot.domain.models.skill import EvolutionEntry, Skill

logger = logging.getLogger(__name__)

__all__ = ["SkillCurator", "ACTIVE_DAYS", "STALE_DAYS"]

ACTIVE_DAYS = 30
"""Skills used within this many days are classified as 'active'."""

STALE_DAYS = 90
"""Skills unused longer than this are 'archive-candidate'; between ACTIVE_DAYS and STALE_DAYS is 'stale'."""

_REVIEW_SYSTEM = (
    "You are a skill portfolio curator. You are given a skill's name, description, "
    "classification (stale or archive-candidate), and a content preview. "
    "Respond with exactly one word on the first line: ARCHIVE, PIN, or KEEP. "
    "Then on the second line, one sentence explaining your recommendation.\n\n"
    "ARCHIVE: skill is obsolete, superseded, or has no foreseeable use.\n"
    "PIN: skill is critically important and should never be auto-archived.\n"
    "KEEP: skill is still relevant but low-usage — keep for now.\n"
)


class SkillCurator:
    """Classify skills by recency and LLM-review stale ones.

    Args:
        registry: SkillRegistry instance to load and update skills from.
        llm: LLMPort instance for cheap review calls.
        cheap_model: Model ID for review calls (defaults to MODEL_BUDGET).
    """

    def __init__(
        self,
        registry: SkillRegistry,
        llm: LLMPort,
        cheap_model: Optional[str] = None,
    ) -> None:
        self._registry = registry
        self._llm = llm
        if cheap_model is None:
            from weebot.config.model_refs import MODEL_BUDGET
            cheap_model = MODEL_BUDGET
        self._cheap_model = cheap_model

    async def run_curation(self) -> dict[str, str]:
        """Classify all skills and LLM-review stale and archive-candidate ones.

        Returns:
            Mapping of skill_name → classification string.
        """
        self._registry.load_all()
        skills = self._registry.list_skills()
        now = datetime.now(timezone.utc)
        results: dict[str, str] = {}

        for skill in skills:
            classification = self._classify(skill, now)
            results[skill.name] = classification
            logger.info("Skill %r classified as: %s", skill.name, classification)

            if classification in ("stale", "archive-candidate"):
                await self._review_and_log(skill, classification, now)

        return results

    @staticmethod
    def _classify(skill: Skill, now: datetime) -> str:
        """Return 'active', 'stale', or 'archive-candidate' for *skill*."""
        age_days: int

        # Prefer the most recent EvolutionEntry timestamp as "last touched" proxy
        if skill.evolution_log:
            last_ts = skill.evolution_log[-1].timestamp
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            age_days = (now - last_ts).days
        elif skill.versions:
            last_v = skill.versions[-1]
            if last_v.accepted_at:
                ts = last_v.accepted_at
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_days = (now - ts).days
            else:
                age_days = 999  # No timestamp → treat as very old
        else:
            # Last resort: use the SKILL.md file's mtime so freshly
            # installed skills are classified as active, not archive-candidate.
            if skill.source_path:
                try:
                    mtime = Path(skill.source_path).stat().st_mtime
                    age_days = (now - datetime.fromtimestamp(mtime, tz=timezone.utc)).days
                except OSError:
                    age_days = 999
            else:
                age_days = 999

        if age_days < ACTIVE_DAYS:
            return "active"
        if age_days < STALE_DAYS:
            return "stale"
        return "archive-candidate"

    async def _review_and_log(
        self, skill: Skill, classification: str, now: datetime
    ) -> None:
        """Call LLM to review *skill* and append the result to its evolution_log."""
        prompt = (
            f"Skill name: {skill.name}\n"
            f"Description: {skill.description}\n"
            f"Classification: {classification}\n"
            f"Content preview:\n{skill.content[:1000]}\n\n"
            "Should this skill be ARCHIVE, PIN, or KEEP?"
        )
        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": _REVIEW_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                model=self._cheap_model,
                temperature=TEMPERATURE_DETERMINISTIC,
                max_tokens=MAX_TOKENS_TINY,
            )
            recommendation = (response.content or "(no response)").strip()
        except Exception as exc:
            logger.warning("LLM review failed for skill %r: %s", skill.name, exc)
            recommendation = f"(review failed: {exc})"

        entry = EvolutionEntry(
            epoch=len(skill.evolution_log),
            narrative=(
                f"[SkillCurator] Classification: {classification}. "
                f"Recommendation: {recommendation}"
            ),
        )

        try:
            updated = skill.add_evolution_entry(entry)
            self._registry.update_skill(updated)
            logger.info(
                "Appended SkillCurator entry to skill %r evolution_log (epoch %d)",
                skill.name,
                entry.epoch,
            )
        except Exception as exc:
            logger.warning(
                "Failed to update evolution_log for skill %r: %s", skill.name, exc
            )

    # ── Overlap detection for consolidation ────────────────────────

    async def detect_overlaps(self) -> list[dict[str, str | float]]:
        """Detect overlapping skills and return merge recommendations.

        For each pair of skills, computes keyword Jaccard similarity.
        Pairs with overlap >= 0.5 are flagged as potential merges.

        Returns:
            List of dicts with keys: skill_a, skill_b, overlap, recommendation.
        """
        from weebot.application.services.skill_curator import _extract_keywords, _keyword_overlap

        skills: list = []
        try:
            skills = self._registry.load_all()
        except Exception:
            logger.warning("SkillCurator overlap: registry load failed")
            return []

        keywords_map: dict[str, set[str]] = {}
        for s in skills:
            text = f"{s.name} {s.description} {s.body}"
            keywords_map[s.name] = _extract_keywords(text)

        recommendations: list[dict[str, str | float]] = []
        names = list(keywords_map.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                overlap = _keyword_overlap(keywords_map[names[i]], keywords_map[names[j]])
                if overlap >= 0.5:
                    recommendations.append({
                        "skill_a": names[i],
                        "skill_b": names[j],
                        "overlap": round(overlap, 2),
                        "recommendation": "Consider merging these skills",
                    })

        return recommendations


# ── Helper functions for overlap detection ──────────────────────────

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
})


def _extract_keywords(text: str, max_keywords: int = 10) -> set[str]:
    """Extract significant keywords from *text* for overlap detection."""
    import re
    tokens = re.findall(r"[a-zA-Z]\w{3,}", text.lower())
    filtered = [t for t in tokens if t not in _STOPWORDS and not t.isdigit()]
    return set(filtered[:max_keywords])


def _keyword_overlap(keywords_a: set[str], keywords_b: set[str]) -> float:
    """Jaccard similarity between two keyword sets."""
    if not keywords_a or not keywords_b:
        return 0.0
    return len(keywords_a & keywords_b) / len(keywords_a | keywords_b)
