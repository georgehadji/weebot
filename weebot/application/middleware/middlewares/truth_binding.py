"""Truth binding middleware — validates assistant responses against deterministic guards."""
from __future__ import annotations

from typing import Any

from weebot.application.middleware.event_middleware import EventMiddleware
from weebot.domain.models.event import AgentEvent, MessageEvent


class TruthBindingMiddleware(EventMiddleware):
    """Validates assistant responses against truth-binding guards.

    If the flow has a ``_truth_binder`` and the event is an assistant
    message, applies the binder.  Rewrites or blocks violations.
    """

    async def process(self, event: AgentEvent, context: dict[str, Any]) -> AgentEvent:
        flow = context.get("flow")
        truth_binder = getattr(flow, "_truth_binder", None) if flow else None
        session = context.get("session")

        if truth_binder is not None and isinstance(event, MessageEvent) and event.role == "assistant":
            the_plan = getattr(flow, "_plan", None) if flow else None
            step = the_plan.current_step if the_plan else None
            facts = session.get_facts() if session else {}

            result = await truth_binder.bind(event.message, {
                "session_events": session.events if session else [],
                "step": step,
                "facts": facts,
            })
            if not result.passed or result.has_rewrites():
                flow._log.info(
                    "Truth binding %s for response (%d violations)",
                    "blocked" if result.has_blockers() else "rewrote",
                    len(result.violations),
                )
                for v in result.violations:
                    flow._log.debug("  Violation [%s]: %s", v.check, v.message)
                event = event.model_copy(update={"message": result.bound_text})

        return event
