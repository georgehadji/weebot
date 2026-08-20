"""MaterializingSkillStore — SkillStorePort decorator that closes the loop.

Every current and future path that promotes a skill to 'trusted' and saves
it — Skill.record_positive_use's usage counter, SkillPromotionGate's
verification gate, a human editing trust via the CLI — goes through
SkillStorePort.save(). Rather than hunting down and modifying every one of
those call sites (including ones not wired yet), this decorator wraps
save() once: any skill saved with trust == 'trusted' is materialized to
disk via SkillMaterializer, making it retrievable in the same process
without a restart. Saves for any other trust tier pass through unchanged.
"""

from __future__ import annotations

import logging

from weebot.application.ports.skill_store_port import SkillStorePort
from weebot.application.services.skill_materializer import SkillMaterializer
from weebot.domain.models.skill import Skill

logger = logging.getLogger(__name__)


class MaterializingSkillStore(SkillStorePort):
    """Decorates a SkillStorePort: materializes on every 'trusted' save.

    Args:
        store: The real SkillStorePort implementation to delegate to.
        materializer: Writes trusted skills to disk and refreshes the live
            retriever's index.
    """

    def __init__(self, store: SkillStorePort, materializer: SkillMaterializer) -> None:
        self._store = store
        self._materializer = materializer

    async def save(self, skill: Skill) -> None:
        await self._store.save(skill)
        if skill.metadata.trust != "trusted":
            return
        try:
            await self._materializer.materialize(skill)
        except Exception as exc:
            logger.warning(
                "Skill '%s' saved as trusted but materialization failed — "
                "it will not be retrievable until the registry next reloads: %s",
                skill.name,
                exc,
            )

    async def load(self, name: str) -> Skill | None:
        return await self._store.load(name)

    async def list_names(self) -> list[str]:
        return await self._store.list_names()

    async def delete(self, name: str) -> bool:
        return await self._store.delete(name)

    async def export_best_md(self, name: str, output_path: str) -> None:
        await self._store.export_best_md(name, output_path)
