"""Workspace checkpoint value objects (H5).

A checkpoint is a point-in-time copy of the workspace's files, taken before an agent turn that
may change them, so the change can be undone. It is not a flow checkpoint (``CheckpointPort``
saves the plan) and not drift detection (``WorkspaceSnapshotPort`` only compares).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CheckpointRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    session_id: str
    turn_id: str
    tree_sha: str
    root: str  # the workspace directory this checkpoint copies
    created_at: datetime
    file_count: int = Field(ge=0)
    reason: str = ""


class RestoreReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    restored: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    # The checkpoint taken just before restoring, so the restore can be undone.
    undo_ref: CheckpointRef | None = None

    @property
    def changed(self) -> int:
        return len(self.restored) + len(self.removed)
