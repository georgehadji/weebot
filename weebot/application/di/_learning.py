"""Learning subsystem bindings mixin for Container (Memento-Skills Phase 0+).

Registers the AutonomousSkillDistiller, the SkillReviewGate that promotes a
distilled skill from quarantined -> candidate, the SkillMaterializer that
bridges a 'trusted' skill from SkillStore (SQLite) into SkillRegistry
(filesystem, what the live retriever actually indexes), and a thin
SkillPublisher that wraps the EventPublisher.  All live-learning paths are
behind feature flags that default to OFF so this mixin is inert until a
phase is explicitly enabled.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class LearningMixin:
    """DI bindings for the deployment-time learning subsystem."""

    def configure_learning(self, *, db_path: str = "./weebot_sessions.db") -> None:
        """Register learning services.  Called from configure_defaults()."""
        self.register("skill_distiller", lambda: self._create_skill_distiller(db_path))
        self.register("skill_publisher", self._create_skill_publisher)
        self.register("skill_materializer", self._create_skill_materializer)
        self.register("skill_review_gate", lambda: self._create_skill_review_gate(db_path))

    # ── factories ─────────────────────────────────────────────────────────────

    def _get_learning_skill_store(self, db_path: str):
        """SkillStore for the live-learning subsystem, materializing-wrapped
        when SKILL_MATERIALIZE_ENABLED. Shared by the distiller and the
        review gate so a save from either path gets the same behavior.

        A fresh SkillStore per call is deliberate, not a missed-singleton
        bug: SkillStore is a thin adapter over a path-keyed connection pool
        (see infrastructure/persistence/connection_pool.py), so any number
        of instances pointed at the same db_path share the same underlying
        data and are interchangeable for save/load/list_names.
        """
        from weebot.config.feature_flags import SKILL_MATERIALIZE_ENABLED
        from weebot.infrastructure.persistence.skill_store import SkillStore

        store = SkillStore(db_path=db_path)
        if not SKILL_MATERIALIZE_ENABLED:
            return store

        from weebot.application.services.materializing_skill_store import (
            MaterializingSkillStore,
        )
        materializer = self.get("skill_materializer")  # type: ignore[attr-defined]
        return MaterializingSkillStore(store=store, materializer=materializer)

    def _create_skill_distiller(self, db_path: str):
        """Build the AutonomousSkillDistiller (flag-guarded; returns NoOp if off)."""
        from weebot.config.feature_flags import LIVE_SKILL_DISTILLATION_ENABLED
        from weebot.application.services.autonomous_learning import (
            AutonomousSkillCreator,
        )
        from weebot.application.ports.llm_port import LLMPort

        if not LIVE_SKILL_DISTILLATION_ENABLED:
            return _NoOpDistiller()

        store = self._get_learning_skill_store(db_path)
        llm = self._maybe_get(LLMPort)  # type: ignore[attr-defined]
        return AutonomousSkillCreator(llm=llm, skill_store=store)

    def _create_skill_review_gate(self, db_path: str):
        """Build the SkillReviewGate that promotes quarantined -> candidate.

        Flag-guarded (SKILL_REVIEW_GATE_ENABLED); returns a NoOp when off,
        matching _create_skill_distiller's shape so callers never need to
        branch on whether the feature is enabled.
        """
        from weebot.config.feature_flags import SKILL_REVIEW_GATE_ENABLED
        from weebot.application.services.skill_review_gate import SkillReviewGate
        from weebot.application.ports.llm_port import LLMPort

        if not SKILL_REVIEW_GATE_ENABLED:
            return _NoOpReviewGate()

        store = self._get_learning_skill_store(db_path)
        llm = self._maybe_get(LLMPort)  # type: ignore[attr-defined]
        return SkillReviewGate(llm=llm, skill_store=store)

    def _create_skill_materializer(self):
        """Build the SkillMaterializer, sharing the live retriever's own
        SkillRegistry so a materialized skill is reloaded into the exact
        registry the executor's retriever indexes — not a disconnected copy.
        """
        from weebot.application.services.skill_materializer import SkillMaterializer

        retriever = self._maybe_get_str("skill_retriever")  # type: ignore[attr-defined]
        registry = getattr(retriever, "registry", None)
        if registry is None:
            # No live retriever configured (e.g. a CLI/offline context) —
            # fall back to a standalone registry so materialize() still
            # writes a valid SKILL.md; it just won't refresh a live index.
            from weebot.application.skills.skill_registry import SkillRegistry
            registry = SkillRegistry()
        return SkillMaterializer(registry=registry, retriever=retriever)

    def _create_skill_publisher(self):
        """Wrap EventPublisher with a typed helper for learning events."""
        from weebot.domain.ports import EventPublisher

        publisher = self._maybe_get(EventPublisher)  # type: ignore[attr-defined]
        return _SkillPublisher(publisher)


# ── lightweight helpers ────────────────────────────────────────────────────────


class _NoOpDistiller:
    """Stand-in used when LIVE_SKILL_DISTILLATION_ENABLED is False."""

    async def analyze_session(self, session: Any, trajectory: Any = None) -> None:
        pass  # intentionally inert


class _NoOpReviewGate:
    """Stand-in used when SKILL_REVIEW_GATE_ENABLED is False."""

    async def apply(self, skill: Any) -> tuple[Any, Any]:
        from weebot.domain.models.skill import SkillReview

        name = getattr(skill, "name", "")
        return skill, SkillReview(skill_name=name, recommendation="reject", promoted=False)


class _SkillPublisher:
    """Thin typed wrapper around EventPublisher for skill lifecycle events."""

    def __init__(self, publisher: Any) -> None:
        self._publisher = publisher

    async def publish_distilled(
        self,
        *,
        session_id: str,
        skill_name: str,
        content_preview: str = "",
        origin: str = "distilled",
    ) -> None:
        if self._publisher is None:
            return
        from weebot.domain.models.event import SkillDistilled

        event = SkillDistilled(
            session_id=session_id,
            skill_name=skill_name,
            content_preview=content_preview[:200],
            origin=origin,
        )
        await self._publisher.publish(event)

    async def publish_promoted(
        self,
        *,
        skill_name: str,
        from_tier: str,
        to_tier: str,
        positive_uses: int = 0,
    ) -> None:
        if self._publisher is None:
            return
        from weebot.domain.models.event import SkillPromoted

        event = SkillPromoted(
            skill_name=skill_name,
            from_tier=from_tier,
            to_tier=to_tier,
            positive_uses=positive_uses,
        )
        await self._publisher.publish(event)
