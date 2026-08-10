"""WorkspaceIntegrityGuard — did an observe-only phase write to the workspace?

LongHorizon-Harness E7b, the MEA loop's integrity axis. Verification is
supposed to read the world and judge it. If it also *changes* the world,
every judgement it produced is about a state that no longer exists, and the
executor's record no longer matches the workspace.

Used as an async context manager so detection is structural — the check
cannot be skipped by an early ``return`` or an exception on some path
nobody thought about, which is exactly how the E7a mutation survived
review for as long as it did.

Detects and reports; never restores. See WorkspaceSnapshotPort for why.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Optional

from weebot.application.ports.workspace_snapshot_port import (
    WorkspaceDrift,
    WorkspaceSnapshotPort,
)
from weebot.domain.models.audit import (
    AuditDimension,
    VerificationStatus,
    Violation,
    ViolationSeverity,
)

_log = logging.getLogger(__name__)


@dataclass
class IntegrityWatch:
    """Result of one guarded episode. Populated when the block exits."""
    status: VerificationStatus = VerificationStatus.NOT_RUN
    reason: str = ""
    drift: Optional[WorkspaceDrift] = None
    violations: list[Violation] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """True only when the check RAN and found nothing.

        NOT_RUN is deliberately not clean — a guard that never executed
        must not read as a guard that passed (E4).
        """
        return self.status is VerificationStatus.PASSED


class WorkspaceIntegrityGuard:
    """Wraps an episode and reports whether the workspace changed during it.

    Args:
        snapshots: Port used to capture and compare workspace state. ``None``
            (legacy flows built without DI) disables the guard — which is
            recorded as NOT_RUN, never as a pass.
    """

    def __init__(self, snapshots: WorkspaceSnapshotPort | None) -> None:
        self._snapshots = snapshots

    @asynccontextmanager
    async def watch(
        self,
        *,
        on_complete: Callable[[IntegrityWatch], None] | None = None,
    ) -> AsyncIterator[IntegrityWatch]:
        """Guard the enclosed block.

        The watch object is filled in on exit — including when the block
        raises or returns early. *on_complete* fires at the same moment, so
        callers that leave via an early ``return`` still get their result
        recorded; code placed after the ``async with`` would not run.

        The guard never raises on its own account: a broken integrity check
        must not take down verification with it.
        """
        watch = IntegrityWatch()

        if self._snapshots is None:
            watch.reason = "no workspace snapshot port wired"
            try:
                yield watch
            finally:
                self._finish(watch, on_complete)
            return

        try:
            before = await self._snapshots.snapshot()
        except Exception as exc:  # pragma: no cover - port contract says it won't
            _log.debug("Workspace baseline snapshot failed", exc_info=True)
            watch.reason = f"baseline snapshot raised: {type(exc).__name__}"
            try:
                yield watch
            finally:
                self._finish(watch, on_complete)
            return

        try:
            yield watch
        finally:
            try:
                drift = await self._snapshots.diff(before)
            except Exception as exc:  # pragma: no cover - defensive
                _log.debug("Workspace drift comparison failed", exc_info=True)
                watch.reason = f"drift comparison raised: {type(exc).__name__}"
            else:
                self._record(watch, drift)
            self._finish(watch, on_complete)

    # ── Internal ─────────────────────────────────────────────────────

    @staticmethod
    def _record(watch: IntegrityWatch, drift: WorkspaceDrift) -> None:
        watch.drift = drift

        if drift.unavailable_reason:
            watch.status = VerificationStatus.NOT_RUN
            watch.reason = drift.unavailable_reason
            return

        if drift.is_clean:
            watch.status = VerificationStatus.PASSED
            return

        watch.status = VerificationStatus.FAILED
        watch.reason = drift.describe()
        watch.violations.append(Violation(
            dimension=AuditDimension.INTEGRITY,
            severity=ViolationSeverity.HIGH,
            description=f"verification modified the workspace it was auditing — {drift.describe()}",
            location=", ".join(drift.paths[:3]),
            recommendation=(
                "Verification must observe, not act. Find the write path and "
                "remove it; the audited state changed underneath the audit."
            ),
        ))

    @staticmethod
    def _finish(
        watch: IntegrityWatch,
        on_complete: Callable[[IntegrityWatch], None] | None,
    ) -> None:
        if watch.status is VerificationStatus.FAILED:
            _log.warning("Workspace integrity FAILED: %s", watch.reason)
        elif watch.status is VerificationStatus.NOT_RUN:
            _log.debug("Workspace integrity check did not run: %s", watch.reason)

        if on_complete is None:
            return
        try:
            on_complete(watch)
        except Exception:
            # A failing reporter must not mask the block's own outcome.
            _log.debug("Workspace integrity on_complete callback failed", exc_info=True)
