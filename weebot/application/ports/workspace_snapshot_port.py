"""WorkspaceSnapshotPort — detect writes to the workspace across an episode.

LongHorizon-Harness E7b. The MEA loop's integrity axis asks a question the
other gates cannot: did a phase that is only supposed to *observe* the
workspace end up *changing* it?

Distinct from StepAuditPort, which checks whether claimed changes really
happened. This port checks the inverse — whether unclaimed changes happened
anyway. StepAuditPort reads ToolEvents, so it is blind to anything a shell
command wrote as a side effect; a snapshot sees the filesystem itself.

Design notes:
  - Snapshots are opaque to the Application layer (C1). Callers hold a
    WorkspaceSnapshot and hand it back to ``diff()``; they never learn
    whether the adapter used git, hashes, or mtimes.
  - Detect and report, never restore. WORKSPACE_ROOT defaults to the
    process's cwd (see config.settings), which in practice is the user's
    whole repository — auto-reverting it would happily destroy concurrent
    edits made by the user or another process. Reporting gives the
    invariant without the blast radius.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """An opaque point-in-time record of the workspace.

    ``backend`` names the strategy that produced it; ``payload`` is that
    strategy's private representation. Application code must treat both as
    opaque and only pass the snapshot back to the adapter that made it.
    """

    backend: str
    payload: Any = None


@dataclass(frozen=True)
class WorkspaceDrift:
    """What changed in the workspace between two points in time."""

    added: tuple[str, ...] = field(default_factory=tuple)
    modified: tuple[str, ...] = field(default_factory=tuple)
    removed: tuple[str, ...] = field(default_factory=tuple)
    truncated: bool = False
    """True when the adapter capped the listing — paths are a sample, not the whole set."""
    unavailable_reason: str = ""
    """Non-empty when drift could not be determined at all.

    Must not be read as "clean": a check that could not run is not a check
    that passed (E4 — fail closed). ``is_clean`` is False in this case.
    """

    @property
    def is_clean(self) -> bool:
        """True only when the check ran AND found nothing."""
        if self.unavailable_reason:
            return False
        return not (self.added or self.modified or self.removed)

    @property
    def paths(self) -> tuple[str, ...]:
        return self.added + self.modified + self.removed

    def describe(self, limit: int = 5) -> str:
        """One-line human summary, for violation descriptions and logs."""
        if self.unavailable_reason:
            return f"drift undetermined: {self.unavailable_reason}"
        if self.is_clean:
            return "no workspace changes"
        counts = (
            f"+{len(self.added)} added, ~{len(self.modified)} modified, "
            f"-{len(self.removed)} removed"
        )
        sample = ", ".join(self.paths[:limit])
        suffix = " (truncated)" if self.truncated else ""
        return f"{counts}{suffix}: {sample}"


class WorkspaceSnapshotPort(ABC):
    """Point-in-time workspace comparison, scoped to the configured root."""

    @abstractmethod
    async def snapshot(self) -> WorkspaceSnapshot:
        """Capture the workspace's current state.

        Must never raise for an unreadable or missing workspace — return a
        snapshot whose later ``diff()`` reports ``unavailable_reason``
        instead, so a broken guard degrades to "unknown", not to a crash
        in the middle of verification.
        """
        ...

    @abstractmethod
    async def diff(self, before: WorkspaceSnapshot) -> WorkspaceDrift:
        """Compare the workspace now against *before*.

        Returns a drift whose ``unavailable_reason`` is set when the
        comparison could not be made — callers must treat that as
        "not verified", never as clean.
        """
        ...
