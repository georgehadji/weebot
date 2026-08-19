"""SessionConstraintAccumulator — hydrates and updates a session's side-constraint registry.

Extracted from PlanActFlow (Lost-in-Compaction Phase 3 — see
tasks/specs/side_constraint_integrity_plan.md) to keep plan_act_flow.py
under its allowlisted line budget, mirroring the FactResolver/ToolAssembler
collaborator pattern already used there.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from weebot.domain.models.event import SessionConstraintRecorded, SessionConstraintRevoked
from weebot.domain.models.session_constraint import (
    ConstraintDirection,
    ConstraintKind,
    SessionConstraint,
    SessionConstraintRegistry,
)

logger = logging.getLogger(__name__)


class SessionConstraintAccumulator:
    """Loads, extracts into, and persists a session's constraint registry.

    Args:
        extractor: SessionConstraintExtractor. Callers should not construct
            this collaborator at all when extraction is disabled — PlanActFlow
            only calls it when cfg.session_constraint_extractor is set.
        state_repo: Optional persistence port (duck-typed: save_session_constraint,
            revoke_session_constraint, list_active_session_constraints). None
            means in-memory-only for this process lifetime.
        event_bus: Optional EventBusPort. When set, publishes
            SessionConstraintRecorded/Revoked as DomainEvents (internal bus
            signals, not AgentEvents — never returned to PlanActFlow.run()'s
            AgentEvent stream).
    """

    def __init__(
        self, extractor: Any, state_repo: Optional[Any] = None,
        event_bus: Optional[Any] = None,
    ) -> None:
        self._extractor = extractor
        self._state_repo = state_repo
        self._event_bus = event_bus

    async def hydrate(self, session_id: str) -> SessionConstraintRegistry:
        """Load active constraints for *session_id* from state_repo.

        Never raises — degrades to an empty registry on any failure so a
        transient persistence issue never blocks the flow.
        """
        if self._state_repo is None:
            return SessionConstraintRegistry()
        try:
            rows = await self._state_repo.list_active_session_constraints(session_id)
        except Exception as exc:
            logger.warning("Failed to load session constraints: %s", exc)
            return SessionConstraintRegistry()
        constraints = [
            SessionConstraint(
                text=r["text"],
                evidence_span=r.get("evidence_span", r["text"]),
                kind=ConstraintKind(r["kind"]),
                direction=ConstraintDirection(r["direction"]),
                turn_index=r.get("turn_index", 0),
            )
            for r in rows
        ]
        return SessionConstraintRegistry(constraints=constraints)

    async def extract_and_apply(
        self, session_id: str, prompt: str, registry: SessionConstraintRegistry,
        turn_index: int,
    ) -> SessionConstraintRegistry:
        """Extract constraints from *prompt*, persist/publish them, and
        return the updated registry. Never raises (plan D9)."""
        try:
            result = await self._extractor.extract(
                prompt, registry=registry, turn_index=turn_index,
            )
        except Exception as exc:
            logger.warning("Session constraint extraction failed: %s", exc)
            return registry

        for c in result.added:
            registry = registry.add(c)
            await self._persist_add(session_id, c)
            await self._publish(SessionConstraintRecorded(
                session_id=session_id, text=c.text,
                kind=c.kind.value, direction=c.direction.value,
            ))

        for text in result.revoked_texts:
            registry = registry.revoke(text)
            await self._persist_revoke(session_id, text)
            await self._publish(SessionConstraintRevoked(session_id=session_id, text=text))

        return registry

    async def _persist_add(self, session_id: str, constraint: SessionConstraint) -> None:
        if self._state_repo is None:
            return
        try:
            await self._state_repo.save_session_constraint(session_id, constraint)
        except Exception as exc:
            logger.warning("Failed to persist session constraint: %s", exc)

    async def _persist_revoke(self, session_id: str, text: str) -> None:
        if self._state_repo is None:
            return
        try:
            await self._state_repo.revoke_session_constraint(
                session_id, text, datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.warning("Failed to persist constraint revocation: %s", exc)

    async def _publish(self, event: Any) -> None:
        if self._event_bus is not None:
            await self._event_bus.publish_domain_event(event)
