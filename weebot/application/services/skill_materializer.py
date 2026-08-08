"""SkillMaterializer — bridges SkillStore (SQLite) to SkillRegistry (filesystem).

Distillation and promotion (``autonomous_learning.py``, ``skill_review_gate.py``)
persist ``Skill`` objects through ``SkillStorePort`` — a SQLite-backed store.
Injection at inference time reads a completely different path: the executor's
skill retrievers (``BM25SkillRetriever`` and friends) are built over
``SkillRegistry``, which parses ``SKILL.md`` files with YAML frontmatter from
disk (``.weebot/skills/``, ``~/.weebot/skills/``, the built-in skills dir).
Nothing ever connected the two — a skill promoted all the way to ``trusted``
in the store still could not be retrieved or injected, because the retriever
never saw it.

This service is that connection: it writes a trusted skill out as a
SKILL.md the registry can parse, then reloads the registry and refreshes the
live retriever's index so the skill becomes retrievable in the same process.
"""
from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from weebot.application.skills.skill_registry import SkillRegistry
from weebot.domain.models.skill import Skill

logger = logging.getLogger(__name__)


class SkillMaterializer:
    """Writes a Skill to disk as SKILL.md and reloads the live registry.

    Args:
        registry: The SkillRegistry instance the executor's retriever(s)
            are built over — must be the SAME instance, not a fresh one,
            or the reload has no effect on what gets retrieved.
        retriever: Optional retriever-like object with a ``refresh()``
            method (BM25SkillRetriever, SemanticSkillRetriever,
            RerankingSkillRetriever all expose one). Refreshed after every
            materialization so the new skill is retrievable immediately,
            not just after the next process restart.
        skills_dir: Directory to write into. Defaults to ``.weebot/skills``
            under the current working directory — the same path
            ``SkillRegistry._default_paths()`` looks for.

    This class does not gate on trust tier — callers decide when to
    materialize (see the wiring in application/di/_learning.py, which only
    calls this after a candidate->trusted promotion). Writing a
    non-trusted skill here is harmless but pointless: the retriever-side
    is_injectable filter (BM25SkillRetriever.refresh() and siblings)
    excludes anything that isn't 'trusted' from the corpus regardless.
    """

    def __init__(
        self,
        registry: SkillRegistry,
        retriever: Optional[Any] = None,
        skills_dir: Optional[Path] = None,
    ) -> None:
        self._registry = registry
        self._retriever = retriever
        self._skills_dir = skills_dir or (Path.cwd() / ".weebot" / "skills")

    async def materialize(self, skill: Skill) -> Path:
        """Write *skill* as SKILL.md, reload the registry, refresh the index.

        Returns the path written. Overwrites any existing SKILL.md for the
        same skill name — materialization is idempotent by design, since a
        skill's content can keep evolving after first promotion.

        async because retriever.refresh() is async on some implementations
        (SemanticSkillRetriever, RerankingSkillRetriever) and sync on others
        (BM25SkillRetriever) — calling an async refresh() without awaiting
        it creates a coroutine that never runs and silently no-ops.
        """
        skill_dir = self._skills_dir / skill.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(self._render(skill), encoding="utf-8")
        logger.info("Materialized skill '%s' -> %s", skill.name, skill_file)

        self._registry.add_search_path(self._skills_dir)
        self._registry.load_all()

        if self._retriever is not None and hasattr(self._retriever, "refresh"):
            try:
                result = self._retriever.refresh()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                logger.warning(
                    "Skill '%s' materialized to disk but retriever refresh "
                    "failed — it will not be retrievable until the next "
                    "refresh: %s", skill.name, exc,
                )

        return skill_file

    @staticmethod
    def _render(skill: Skill) -> str:
        """Render *skill* as a SKILL.md matching SkillRegistry._parse_skill()'s
        expected frontmatter shape: name, description, metadata.trust."""
        frontmatter = {
            "name": skill.name,
            "description": skill.description,
            "metadata": {"trust": skill.metadata.trust},
        }
        header = yaml.safe_dump(frontmatter, sort_keys=False).strip()
        return f"---\n{header}\n---\n\n{skill.content}\n"
