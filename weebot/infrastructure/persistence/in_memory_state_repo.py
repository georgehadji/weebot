"""In-memory state repository for testing and lightweight use."""
from __future__ import annotations

from typing import Dict, List, Optional

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.checkpoint import FlowCheckpoint
from weebot.domain.models.session import Session, SessionStatus


class InMemoryStateRepository(StateRepositoryPort):
    """In-memory session store. Not persistent across restarts."""

    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}
        self._checkpoints: Dict[str, FlowCheckpoint] = {}

    async def save_session(self, session: Session) -> None:
        self._sessions[session.id] = session.model_copy()

    async def load_session(self, session_id: str) -> Optional[Session]:
        session = self._sessions.get(session_id)
        return session.model_copy() if session else None

    async def list_sessions(self, user_id: Optional[str] = None) -> List[Session]:
        sessions = list(self._sessions.values())
        if user_id:
            sessions = [s for s in sessions if s.user_id == user_id]
        return [s.model_copy() for s in sessions]

    async def update_session_status(self, session_id: str, status: SessionStatus) -> None:
        session = self._sessions.get(session_id)
        if session:
            self._sessions[session_id] = session.set_status(status)

    async def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    async def search_sessions(self, query: str, limit: int = 20) -> list[dict]:
        return []

    async def get_low_salience_entries(
        self, threshold: float = 0.3, limit: int = 50
    ) -> list[dict]:
        return []

    # ── Checkpoint operations (last-write-wins per session) ────────

    async def save_checkpoint(self, checkpoint: FlowCheckpoint) -> None:
        self._checkpoints[checkpoint.session_id] = checkpoint.model_copy(deep=True)

    async def load_checkpoint(self, session_id: str) -> Optional[FlowCheckpoint]:
        checkpoint = self._checkpoints.get(session_id)
        return checkpoint.model_copy(deep=True) if checkpoint else None

    async def delete_checkpoint(self, session_id: str) -> bool:
        return self._checkpoints.pop(session_id, None) is not None

    async def list_checkpointed_sessions(self) -> list[str]:
        return list(self._checkpoints.keys())
