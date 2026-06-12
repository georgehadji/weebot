"""EventEmitter — extracted from PlanActFlow to reduce God-object complexity.

Handles:
- Event emission with credential sanitization
- Truth-binding validation
- Domain event publishing
- Hook execution
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

from weebot.domain.models.event import (
    AgentEvent,
    MessageEvent,
    PlanStepCompleted,
    FactDiscovered,
)

if TYPE_CHECKING:
    from weebot.application.ports.event_bus_port import EventBusPort
    from weebot.application.ports.checkpoint_port import CheckpointPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.core.structured_logger import StructuredLogger
    from weebot.domain.models.session import Session
    from weebot.domain.models.plan import Plan

logger = logging.getLogger(__name__)


class EventEmitter:
    """Publishes events with credential redaction, truth binding, and hook dispatch."""

    def __init__(
        self,
        event_bus: Optional["EventBusPort"] = None,
        state_repo: Optional["StateRepositoryPort"] = None,
        checkpoint_port: Optional["CheckpointPort"] = None,
        truth_binder: Any = None,
        hooks: Any = None,
        logger_obj: Optional["StructuredLogger"] = None,
    ):
        self._event_bus = event_bus
        self._state_repo = state_repo
        self._checkpoint_port = checkpoint_port
        self._truth_binder = truth_binder
        self._hooks = hooks
        self._log = logger_obj or logger
        self._emit_lock = asyncio.Lock()
        self._persistence_adapter = None

    async def emit(
        self,
        event: AgentEvent,
        session: "Session",
        plan: Optional["Plan"] = None,
    ) -> "Session":
        """Publish an event through all channels: memory, bus, persistence.

        Returns the updated session (with event appended).
        """
        # 1. Truth-binding for assistant responses
        if (
            self._truth_binder is not None
            and isinstance(event, MessageEvent)
            and event.role == "assistant"
        ):
            result = await self._truth_binder.bind(
                event.message,
                {
                    "session_events": session.events,
                    "step": plan.current_step if plan else None,
                    "facts": session.get_facts(),
                },
            )
            if not result.passed or result.has_rewrites():
                self._log.info(
                    "Truth binding %s for response (%d violations)",
                    "blocked" if result.has_blockers() else "rewrote",
                    len(result.violations),
                )
                event = event.model_copy(update={"message": result.bound_text})

        # 2. Credential redaction for user input
        if isinstance(event, MessageEvent) and event.role == "user":
            from weebot.core.credential_sanitizer import sanitize
            sanitized = sanitize(event.message or "")
            if sanitized != event.message:
                event = event.model_copy(update={"message": sanitized})
                self._log.info("Credential sanitizer redacted user input")

        # 3. Append to in-memory session
        session = session.add_event(event)

        # 4. Save checkpoint after step events
        if event.type == "step" and self._checkpoint_port and plan:
            await self._maybe_save_checkpoint(session, plan)

        # 5. Publish to event bus
        if self._event_bus:
            await self._event_bus.publish(event)
            await self._emit_domain_event(event, session)

        # 6. Persist to DB
        if self._state_repo:
            async with self._emit_lock:
                adapter = self._get_persistence_adapter()
                if adapter is not None:
                    ok = await adapter.save_session(session)
                    if not ok:
                        self._log.error(
                            "Session %s dead-lettered", session.id,
                        )
                else:
                    try:
                        await self._state_repo.save_session(session)
                    except Exception as exc:
                        self._log.warning("Session persistence failed: %s", exc)

        return session

    async def _emit_domain_event(self, event: AgentEvent, session: "Session") -> None:
        """Publish domain events derived from agent events."""
        if not self._event_bus:
            return

        if event.type == "step":
            step_id = getattr(event, "step_id", None) or getattr(event, "id", "unknown")
            await self._event_bus.publish_domain_event(
                PlanStepCompleted(session_id=session.id, step_id=str(step_id))
            )

        if event.type in ("message", "thought") and hasattr(event, "message"):
            msg = getattr(event, "message", "")
            if isinstance(msg, str) and len(msg) > 50:
                from hashlib import md5
                key = md5(msg.encode()).hexdigest()[:12]
                await self._event_bus.publish_domain_event(
                    FactDiscovered(session_id=session.id, key=key, value=msg[:500])
                )

    async def _maybe_save_checkpoint(self, session: "Session", plan: "Plan") -> None:
        """Save a flow checkpoint after each completed step."""
        if self._checkpoint_port is None:
            return
        try:
            from weebot.domain.models.checkpoint import FlowCheckpoint, StepCheckpoint
            completed = [
                StepCheckpoint(
                    step_id=s.id, description=s.description,
                    status=s.status.value, result=s.result,
                )
                for s in plan.steps if s.status.value in ("completed", "failed")
            ]
            checkpoint = FlowCheckpoint(
                session_id=session.id,
                flow_type="PlanActFlow",
                current_state="executing",
                plan_snapshot=plan,
                completed_steps=completed,
                conversation_summary="",
                iteration_count=0,
            )
            await self._checkpoint_port.save(checkpoint)
        except Exception:
            self._log.warning("Checkpoint save failed", exc_info=True)

    def _get_persistence_adapter(self):
        """Lazy-resolve session persistence adapter."""
        if self._persistence_adapter is None:
            try:
                from weebot.application.di import Container
                c = Container()
                c.configure_defaults()
                self._persistence_adapter = c.get("session_persistence")
            except (KeyError, Exception):
                return None
        return self._persistence_adapter
