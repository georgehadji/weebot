"""Session deletion orchestrator.

Ensures that deleting a session cleans up data across all persistence stores.
Each store is called in turn; a failure in one does not block deletion in others.
"""
from __future__ import annotations

import logging
from typing import Any

from weebot.application.ports.state_repo_port import StateRepositoryPort

logger = logging.getLogger(__name__)


class SessionDeletionOrchestrator:
    """Coordinates session deletion across known persistence stores.

    Stores are wired by name so the orchestrator can be used from the web
    layer without importing infrastructure adapters directly.
    """

    def __init__(
        self,
        state_repo: StateRepositoryPort,
    ):
        self._state_repo = state_repo
        self._extras: list[tuple[str, Any, str]] = []
        # Each extra is (name, instance, method_name)

    def add_store(self, name: str, instance: Any, method: str = "delete_session") -> None:
        """Register an additional store for session-scoped cleanup.

        Args:
            name: Human-readable store name (for logging).
            instance: The store object.
            method: Async method name on *instance* that accepts ``session_id``.
        """
        self._extras.append((name, instance, method))

    async def delete_session(self, session_id: str) -> dict[str, str]:
        """Delete *session_id* data from all known stores.

        Returns a dict mapping store names to status strings (``"ok"`` or
        ``"error: see server logs"``).
        """
        results: dict[str, str] = {}

        # 1. Primary state repository (sessions table + FTS index)
        try:
            await self._state_repo.delete_session(session_id)
            results["state_repo"] = "ok"
        except Exception:
            logger.exception("state_repo.delete_session failed for %s", session_id)
            results["state_repo"] = "error: see server logs"

        # 2. Extra stores (event store, checkpoint store, etc.)
        for name, instance, method_name in self._extras:
            try:
                method = getattr(instance, method_name, None)
                if method is not None:
                    await method(session_id)
                results[name] = "ok"
            except Exception:
                logger.exception("%s.%s failed for %s", name, method_name, session_id)
                results[name] = "error: see server logs"

        return results
