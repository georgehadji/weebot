"""Port for undoable workspace checkpoints (H5).

Unlike ``CheckpointPort`` (the plan, per session) and ``WorkspaceSnapshotPort`` (detects drift,
"never restore"), this one can put files back.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from weebot.domain.models.workspace_checkpoint import CheckpointRef, RestoreReport


class WorkspaceCheckpointPort(ABC):
    @abstractmethod
    async def snapshot(
        self, *, session_id: str, turn_id: str, root: Path, reason: str
    ) -> CheckpointRef | None:
        """Checkpoint *root* once per (session, turn).

        Returns None when nothing was taken: already done this turn, nothing changed since the
        last one, the workspace is over the size caps, or the backend is unavailable. Never
        raises for those; a checkpoint must not block the tool call it guards.
        """

    @abstractmethod
    async def list(self, session_id: str, limit: int = 50) -> list[CheckpointRef]:
        """The session's checkpoints, newest first."""

    @abstractmethod
    async def diff(self, ref: CheckpointRef, *, paths: Sequence[str] = ()) -> str:
        """Unified diff from *ref* to the workspace as it is now."""

    @abstractmethod
    async def restore(self, ref: CheckpointRef, *, paths: Sequence[str] = ()) -> RestoreReport:
        """Put the workspace (or *paths*) back to *ref*; snapshots first so it can be undone."""

    @abstractmethod
    async def gc(self, *, older_than_days: int) -> int:
        """Delete checkpoints older than the cutoff. Returns how many."""

    @abstractmethod
    async def delete_session(self, session_id: str) -> int:
        """Delete every checkpoint of a session (session-delete cascade). Returns how many."""
