"""Human-in-the-loop interaction service."""
from __future__ import annotations

import asyncio
from typing import Dict, Optional


class HumanInteractionService:
    """Async-safe singleton for managing pending human questions."""

    def __init__(self) -> None:
        self._pending: Dict[str, asyncio.Future[str]] = {}

    def ask(self, session_id: str, question: str) -> asyncio.Future[str]:
        """Create a pending future for a human question."""
        if session_id in self._pending and not self._pending[session_id].done():
            raise RuntimeError(f"Session {session_id} already has a pending question")
        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        self._pending[session_id] = future
        return future

    def answer(self, session_id: str, answer: str) -> bool:
        """Resolve a pending future with the human's answer."""
        future = self._pending.pop(session_id, None)
        if future is None or future.done():
            return False
        future.set_result(answer)
        return True

    def has_pending(self, session_id: str) -> bool:
        """Check if the session has an unresolved question."""
        future = self._pending.get(session_id)
        return future is not None and not future.done()

    def cancel(self, session_id: str) -> bool:
        """Cancel a pending future."""
        future = self._pending.pop(session_id, None)
        if future is None or future.done():
            return False
        future.cancel()
        return True


# Global singleton instance
_global_hitl_service: HumanInteractionService | None = None


def get_human_interaction_service() -> HumanInteractionService:
    """Get the global HITL service singleton."""
    global _global_hitl_service
    if _global_hitl_service is None:
        _global_hitl_service = HumanInteractionService()
    return _global_hitl_service
