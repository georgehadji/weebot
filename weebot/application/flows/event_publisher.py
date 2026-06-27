"""EventPublisher — single responsibility for publishing typed agent events.

Extracted from ``PlanActFlow._emit()`` to isolate the truth-binding, credential
sanitization, session mutation, event bus publishing, and persistence concerns
into their own class.

Usage:
    publisher = EventPublisher(session=session, event_bus=event_bus,
                                state_repo=state_repo, ...)
    await publisher.emit(event)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from weebot.domain.models.event import AgentEvent, MessageEvent
from weebot.domain.models.session import Session
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.state_repo_port import StateRepositoryPort

logger = logging.getLogger(__name__)


class EventPublisher:
    """Publishes agent events through the full pipeline.

    Pipeline:
        1. Truth-binding (optional)
        2. Credential sanitization
        3. Session mutation + checkpoint
        4. Event bus publish + domain events
        5. DB persistence
    """

    def __init__(
        self,
        session: Session,
        event_bus: Optional[EventBusPort] = None,
        state_repo: Optional[StateRepositoryPort] = None,
        truth_binder: Optional[Any] = None,
        plan: Optional[Any] = None,
        persistence_adapter: Optional[Any] = None,
        hooks: Optional[Any] = None,
        emit_lock: Optional[asyncio.Lock] = None,
    ) -> None:
        self._session = session
        self._event_bus = event_bus
        self._state_repo = state_repo
        self._truth_binder = truth_binder
        self._plan = plan
        self._persistence_adapter = persistence_adapter
        self._hooks = hooks
        self._emit_lock = emit_lock or asyncio.Lock()

    # ── Public API ─────────────────────────────────────────────────────────

    async def emit(self, event: AgentEvent) -> Session:
        """Process an event through the full pipeline.

        Returns the (potentially mutated) session.
        """
        # 1. Truth-binding
        event = await self._apply_truth_binding(event)
        # 2. Credential sanitization
        event = self._apply_credential_sanitization(event)
        # 3. Session mutation
        self._session = self._session.add_event(event)
        if event.type == "step":
            await self._maybe_save_checkpoint()
        # 4. Event bus publishing
        if self._event_bus:
            await self._event_bus.publish(event)
            await self._emit_domain_event(event)
        # 5. DB persistence
        if self._state_repo:
            await self._persist_session()
        return self._session

    # ── Step 1: Truth binding ─────────────────────────────────────────────

    async def _apply_truth_binding(self, event: AgentEvent) -> AgentEvent:
        if (
            self._truth_binder is not None
            and isinstance(event, MessageEvent)
            and event.role == "assistant"
        ):
            result = await self._truth_binder.bind(
                event.message,
                {
                    "session_events": self._session.events,
                    "step": self._plan.current_step if self._plan else None,
                    "facts": self._session.get_facts(),
                },
            )
            if not result.passed or result.has_rewrites():
                logger.info(
                    "Truth binding %s for response (%d violations)",
                    "blocked" if result.has_blockers() else "rewrote",
                    len(result.violations),
                )
                event = event.model_copy(update={"message": result.bound_text})
        return event

    # ── Step 2: Credential sanitization ────────────────────────────────────

    @staticmethod
    def _apply_credential_sanitization(event: AgentEvent) -> AgentEvent:
        if isinstance(event, MessageEvent) and event.role == "user":
            from weebot.core.credential_sanitizer import sanitize
            sanitized = sanitize(event.message or "")
            if sanitized != event.message:
                event = event.model_copy(update={"message": sanitized})
                logger.info("Credential sanitizer redacted user input")
        return event

    # ── Step 3: Checkpoint ─────────────────────────────────────────────────

    async def _maybe_save_checkpoint(self) -> None:
        """Save a flow checkpoint if a CheckpointPort is wired."""
        if self._hooks is not None:
            try:
                await self._hooks.execute_hooks("checkpoint", {
                    "session_id": self._session.id,
                    "step_id": getattr(
                        self._plan, "current_step", None
                    ),
                })
            except Exception:
                logger.debug("Checkpoint hook failed", exc_info=True)

    # ── Step 4: Domain events ─────────────────────────────────────────────

    async def _emit_domain_event(self, event: AgentEvent) -> None:
        """Publish domain events derived from agent events."""
        if not self._event_bus:
            return

        from weebot.domain.models.event import PlanStepCompleted, FactDiscovered

        if event.type == "step":
            step_id = getattr(event, "step_id", None) or getattr(event, "id", "unknown")
            domain_event = PlanStepCompleted(
                session_id=self._session.id,
                step_id=str(step_id),
            )
            await self._event_bus.publish_domain_event(domain_event)

        if event.type in ("message", "thought") and hasattr(event, "message"):
            msg = getattr(event, "message", "")
            if isinstance(msg, str) and len(msg) > 50:
                from hashlib import md5
                key = md5(msg.encode()).hexdigest()[:12]
                domain_event = FactDiscovered(
                    session_id=self._session.id,
                    key=key,
                    value=msg[:500],
                )
                await self._event_bus.publish_domain_event(domain_event)

    # ── Step 5: Persistence ────────────────────────────────────────────────

    async def _persist_session(self) -> None:
        if self._persistence_adapter is not None:
            ok = await self._persistence_adapter.save_session(self._session)
            if not ok:
                logger.error(
                    "Session %s dead-lettered — persistence exhausted retries",
                    self._session.id,
                )
        else:
            try:
                await self._state_repo.save_session(self._session)
            except Exception as exc:
                logger.warning("Session persistence failed (retryable): %s", exc)
