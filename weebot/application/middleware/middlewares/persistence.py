"""Persistence middleware — saves session state to the database.

Runs last in the pipeline.  Uses a lock for serial DB writes.
"""
from __future__ import annotations

from typing import Any

from weebot.application.middleware.event_middleware import EventMiddleware
from weebot.domain.models.event import AgentEvent


class PersistenceMiddleware(EventMiddleware):
    """Persists the updated session to the database.

    Uses ``SessionPersistenceAdapter`` when available (retry + dead-letter);
    falls back to ``state_repo.save_session()`` for backward compat.
    """

    async def process(self, event: AgentEvent, context: dict[str, Any]) -> AgentEvent:
        flow = context.get("flow")
        state_repo = context.get("state_repo")
        session = context.get("session")

        if state_repo is None or session is None or flow is None:
            return event

        emit_lock = context.get("emit_lock")
        if emit_lock is not None:
            async with emit_lock:
                await self._persist(flow, state_repo, session)
        else:
            await self._persist(flow, state_repo, session)

        return event

    async def _persist(self, flow: Any, state_repo: Any, session: Any) -> None:
        """Perform the actual DB write."""
        adapter = getattr(flow, "_get_persistence_adapter", None)
        if adapter is not None:
            pa = adapter()
            if pa is not None:
                ok = await pa.save_session(session)
                if not ok:
                    flow._log.error(
                        "Session %s dead-lettered — persistence exhausted retries",
                        session.id,
                    )
                return

        try:
            await state_repo.save_session(session)
        except Exception as exc:
            flow._log.warning("Session persistence failed (retryable): %s", exc)
