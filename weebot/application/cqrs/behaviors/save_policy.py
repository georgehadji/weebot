"""SavePolicyBehavior — persists session state after every successful command.

Registered as a pipeline behavior in the CQRS mediator, this eliminates the
need for each flow to remember to call save_session() in _emit().  After any
command with a ``session_id`` field completes successfully, the behavior loads
the session from the repository and saves it back, ensuring all events and
state changes are durable.

This replaces the ad-hoc save_session() calls in PlanActFlow._emit() and
ChatFlow._emit(), providing a single, consistent persistence policy.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from weebot.application.cqrs.base import (
    Command,
    CommandResult,
    IPipelineBehavior,
    Query,
)
from weebot.application.ports.state_repo_port import StateRepositoryPort

logger = logging.getLogger(__name__)


class SavePolicyBehavior(IPipelineBehavior):
    """Pipeline behavior that persists session state after every command.

    Only activates for commands that have a ``session_id`` field (string).
    After the handler returns a successful ``CommandResult``, the session
    is reloaded and saved to the state repository.

    If no ``StateRepositoryPort`` is available, the behavior silently skips
    persistence (logging a warning on the first occurrence).
    """

    def __init__(self, state_repo: StateRepositoryPort | None = None):
        self._state_repo = state_repo
        self._warned: bool = False

    async def handle(
        self,
        request: Command | Query,
        next_callable: Callable[[], Any],
    ) -> Any:
        """Execute the next behavior in the pipeline, then persist."""
        result = await next_callable()

        # Only persist command results (queries are read-only)
        if not isinstance(request, Command) or not isinstance(result, CommandResult):
            return result

        if not result.success:
            return result

        # Check if the command has a session_id
        session_id = getattr(request, "session_id", None)
        if not session_id or not isinstance(session_id, str):
            return result

        if self._state_repo is None:
            if not self._warned:
                logger.warning(
                    "SavePolicyBehavior: no StateRepositoryPort available — "
                    "session %s will NOT be persisted",
                    session_id,
                )
                self._warned = True
            return result

        try:
            session = await self._state_repo.load_session(session_id)
            if session is not None:
                await self._state_repo.save_session(session)
        except Exception:
            logger.exception(
                "SavePolicyBehavior: failed to persist session %s", session_id
            )

        return result
