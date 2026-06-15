"""Learning subsystem bindings mixin for Container (Memento-Skills Phase 0+).

Registers the AutonomousSkillDistiller and a thin SkillPublisher that wraps
the EventPublisher.  All live-learning paths are behind feature flags that
default to OFF so this mixin is inert until a phase is explicitly enabled.
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

    # ── factories ─────────────────────────────────────────────────────────────

    def _create_skill_distiller(self, db_path: str):
        """Build the AutonomousSkillDistiller (flag-guarded; returns NoOp if off)."""
        from weebot.config.feature_flags import LIVE_SKILL_DISTILLATION_ENABLED
        from weebot.application.services.autonomous_learning import (
            AutonomousSkillCreator,
        )
        from weebot.infrastructure.persistence.skill_store import SkillStore
        from weebot.application.ports.llm_port import LLMPort

        if not LIVE_SKILL_DISTILLATION_ENABLED:
            return _NoOpDistiller()

        store = SkillStore(db_path=db_path)
        llm = self._maybe_get(LLMPort)  # type: ignore[attr-defined]
        return AutonomousSkillCreator(llm=llm, skill_store=store)

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
