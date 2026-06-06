"""CheckpointPort — abstract interface for flow checkpoint persistence.

Decouples flow state serialization from storage so that checkpoint stores
(SQLite, filesystem, cloud) can be swapped without touching flow logic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.checkpoint import FlowCheckpoint


class CheckpointPort(ABC):
    """Abstract interface for persisting and retrieving flow checkpoints."""

    @abstractmethod
    async def save(self, checkpoint: FlowCheckpoint) -> None:
        """Persist a checkpoint, overwriting any existing one for the session.

        Only the latest checkpoint per session_id is retained (last-write-wins).
        """
        ...

    @abstractmethod
    async def load(self, session_id: str) -> FlowCheckpoint | None:
        """Load the most recent checkpoint for a session, or None."""
        ...

    @abstractmethod
    async def delete(self, session_id: str) -> bool:
        """Delete the checkpoint for a session. Returns True if one existed."""
        ...

    @abstractmethod
    async def list_checkpointed_sessions(self) -> list[str]:
        """Return session IDs that have a saved checkpoint."""
        ...
