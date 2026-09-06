"""Credential sanitizer middleware — redacts secrets from user input before storage."""

from __future__ import annotations

from typing import Any

from weebot.application.middleware.event_middleware import EventMiddleware
from weebot.domain.models.event import AgentEvent


class CredentialSanitizerMiddleware(EventMiddleware):
    """Redacts passwords, tokens, and API keys from user-originated messages.

    Runs before session storage so secrets never hit the DB or event bus.
    """

    async def process(self, event: AgentEvent, context: dict[str, Any]) -> AgentEvent:
        from weebot.core.credential_sanitizer import sanitize_event

        sanitized = sanitize_event(event)
        if sanitized is not event:
            flow = context.get("flow")
            if flow:
                flow._log.info("Credential sanitizer redacted a %s event", event.type)

        return sanitized
