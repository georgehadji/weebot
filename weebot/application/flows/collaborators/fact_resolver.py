"""FactResolver — resolves facts from session state for agent context.

Extracted from PlanActFlow during architecture remediation (Step 2.2.1).
"""

from __future__ import annotations

from typing import Any

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session


class FactResolver:
    """Resolves facts from session state for agent context.

    Facts are key-value pairs loaded from the session's fact store,
    enriched with prompt context, and returned as a flat dictionary
    for injection into planner/executor prompts.
    """

    def __init__(self, state_repo: StateRepositoryPort) -> None:
        self._state = state_repo

    def resolve_for_session(self, session: Session) -> dict[str, Any]:
        """Resolve facts from a session's fact store.

        Args:
            session: The current session.

        Returns:
            Dict of fact key-value pairs.
        """
        return session.get_facts() if hasattr(session, "get_facts") else {}

    async def resolve_by_id(self, session_id: str) -> dict[str, Any]:
        """Load session and resolve its facts by session ID.

        Args:
            session_id: The session to load facts from.

        Returns:
            Dict of fact key-value pairs, or empty dict if session not found.
        """
        session = await self._state.load_session(session_id)
        if session is None:
            return {}
        return self.resolve_for_session(session)
