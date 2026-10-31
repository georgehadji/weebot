"""Who may see an event on a shared stream: one rule for WebSocket and SSE.

``SessionPresenceEvent`` names the session that changed in ``about_session_id`` and leaves
``session_id`` empty, so it travels on the global channel. It carries a title derived from the
owner's prompt, so only that owner may see it (when ownership is enforced). The WebSocket
broadcaster and the SSE route both ask this module, so the two transports cannot disagree.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.event import AgentEvent, SessionPresenceEvent
from weebot.interfaces.web.auth import (
    current_principal,
    ownership_enforced,
    verify_session_ownership,
)


def presence_owner(event: Any, enforced: bool) -> str | None:
    """The one principal allowed to see *event*, or None when everyone may."""
    if isinstance(event, SessionPresenceEvent) and event.owner_user_id and enforced:
        return event.owner_user_id
    return None


def visible_to(event: Any, principal: str | None, enforced: bool) -> bool:
    owner = presence_owner(event, enforced)
    return owner is None or owner == principal


class EventVisibility:
    """The filter one SSE connection applies to the events it is about to send."""

    def __init__(self, request: Request, state_repo: StateRepositoryPort) -> None:
        self._request = request
        self._state_repo = state_repo
        self._by_session: dict[str, bool] = {}

    async def __call__(self, event: AgentEvent) -> bool:
        sid = getattr(event, "session_id", "") or ""
        if not sid:
            # A process-level notice, or a presence frame that routes by owner instead.
            if isinstance(event, SessionPresenceEvent):
                principal = await current_principal(self._request)
                return visible_to(event, principal, ownership_enforced())
            return True
        if sid in self._by_session:
            return self._by_session[sid]
        session = await self._state_repo.load_session(sid)
        try:
            await verify_session_ownership(self._request, session.user_id if session else None)
            allowed = True
        except HTTPException:
            allowed = False
        if session is not None:
            # Not before the session exists: "nothing to check yet" is not a verdict, and
            # another principal may create it a moment later.
            self._by_session[sid] = allowed
        return allowed
