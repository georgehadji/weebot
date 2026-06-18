"""Audit middleware — records every event to the append-only audit log.

Plugs into the EventPipeline built in WP-4.  Each event is recorded
with its type, model dump, and flow context before reaching the
persistence layer.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from weebot.application.middleware.event_middleware import EventMiddleware
from weebot.domain.models.event import AgentEvent

if TYPE_CHECKING:
    from weebot.infrastructure.observability.audit_log import AuditLog


class AuditMiddleware(EventMiddleware):
    """Records every flow event to the append-only audit log.

    Runs early in the pipeline (after credential sanitization but before
    session mutation) so the audit trail captures the sanitized event
    before it reaches persistent storage.
    """

    def __init__(self, audit_log: "AuditLog | None" = None) -> None:
        self._audit_log = audit_log or AuditLog()

    async def process(self, event: AgentEvent, context: dict[str, Any]) -> AgentEvent:
        if self._audit_log is not None:
            await self._audit_log.record(
                event_type=event.type,
                details={
                    "session_id": context.get("session_id", ""),
                    "flow_type": "plan_act",
                    "event": event.model_dump(mode="json"),
                },
            )
        return event
