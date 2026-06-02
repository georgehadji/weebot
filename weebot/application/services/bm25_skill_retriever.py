"""BM25SkillRetriever — BM25-based skill retrieval (Tier 1.2).

Indexes all loaded skills at construction time using BM25Okapi.
When rank_bm25 is not installed, falls back to simple word-overlap scoring.

Maps to LIFE-HARNESS "Procedural Skill Layer" (Section 4.3.2).
"""
from __future__ import annotations

import logging
from typing import Optional

from weebot.application.ports.skill_retriever_port import SkillRetrieverPort
from weebot.application.skills.skill_registry import SkillRegistry
from weebot.domain.models.skill import SkillMatch

logger = logging.getLogger(__name__)

try:
    from rank_bm25 import BM25Okapi
    HAS_BM25 = True
except ImportError:
    BM25Okapi = None  # type: ignore[assignment,misc]
    HAS_BM25 = False
    logger.warning("rank_bm25 not installed — BM25SkillRetriever uses word-overlap fallback")


class BM25SkillRetriever(SkillRetrieverPort):
    """BM25-based skill retrieval over the skill registry.

    Args:
        registry: Loaded SkillRegistry instance.
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry
        self._corpus: list[str] = []
        self._skill_names: list[str] = []
        self._bm25: Optional["BM25Okapi"] = None
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the BM25 index from the current skill registry."""
        registry = self._registry
        skills = registry.list_all() if hasattr(registry, "list_all") else self._load_all(registry)

        self._corpus = []
        self._skill_names = []

        for skill_name, skill in skills.items() if isinstance(skills, dict) else skills:
            desc = getattr(skill, "description", "") or ""
            content = getattr(skill, "content", "") or ""
            text = f"{desc} {content[:500]}"
            if text.strip():
                self._corpus.append(text)
                self._skill_names.append(
                    skill_name if isinstance(skill_name, str) else getattr(skill, "name", "?")
                )

        if HAS_BM25 and self._corpus:
            try:
                tokenized = [doc.split() for doc in self._corpus]
                self._bm25 = BM25Okapi(tokenized)
                logger.info(
                    "BM25 index built: %d skills", len(self._corpus)
                )
            except Exception as exc:
                logger.warning("BM25 index build failed: %s — using fallback", exc)
                self._bm25 = None
        else:
            logger.info("Word-overlap index built: %d skills", len(self._corpus))

    @staticmethod
    def _load_all(registry):
        """Get all skills from the registry, whichever method it supports."""
        names = registry.list_names() if hasattr(registry, "list_names") else []
        result = {}
        for name in names:
            skill = registry.get(name) if hasattr(registry, "get") else None
            if skill is not None:
                result[name] = skill
        return result

    async def retrieve(self, task: str, top_k: int = 3) -> list[SkillMatch]:
        """Return top-k skills most relevant to *task*."""
        if not self._corpus:
            return []

        tokens = task.split()

        if HAS_BM25 and self._bm25 is not None:
            scores = self._bm25.get_scores(tokens)
        else:
            # Fallback: word-overlap scoring
            scores = []
            for doc in self._corpus:
                doc_tokens = set(doc.lower().split())
                overlap = sum(1 for t in tokens if t.lower() in doc_tokens)
                scores.append(overlap / max(len(tokens), 1))

        # Zip, normalize, sort
        scored = list(zip(self._skill_names, self._corpus, scores))
        if not any(s > 0 for _, _, s in scored):
            return []

        max_score = max(s for _, _, s in scored)
        if max_score > 0:
            scored = [(n, c, s / max_score) for n, c, s in scored]

        scored.sort(key=lambda x: x[2], reverse=True)

        results = []
        for name, text, score in scored[:top_k]:
            # Preview: first 300 chars of relevant content
            preview = text[:300]
            results.append(
                SkillMatch(
                    skill_name=name,
                    description=text[:100],
                    content_preview=preview,
                    score=round(score, 4),
                )
            )

        return results
