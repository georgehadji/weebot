"""Tests for WorkspaceIntegrityGuard (LongHorizon-Harness E7b).

The guard's contract is mostly about the awkward paths: early returns,
exceptions, and a snapshot backend that cannot answer. Those are where a
trailing "did anything change?" check would quietly not run — which is the
whole reason this is a context manager.
"""

from __future__ import annotations

import pytest

from weebot.application.ports.workspace_snapshot_port import (
    WorkspaceDrift,
    WorkspaceSnapshot,
    WorkspaceSnapshotPort,
)
from weebot.application.services.workspace_integrity_guard import (
    IntegrityWatch,
    WorkspaceIntegrityGuard,
)
from weebot.domain.models.audit import AuditDimension, VerificationStatus, ViolationSeverity


class _StubSnapshots(WorkspaceSnapshotPort):
    def __init__(self, drift: WorkspaceDrift) -> None:
        self._drift = drift
        self.snapshots_taken = 0
        self.diffs_taken = 0

    async def snapshot(self) -> WorkspaceSnapshot:
        self.snapshots_taken += 1
        return WorkspaceSnapshot(backend="stub", payload={})

    async def diff(self, before: WorkspaceSnapshot) -> WorkspaceDrift:
        self.diffs_taken += 1
        return self._drift


_CLEAN = WorkspaceDrift()
_DIRTY = WorkspaceDrift(modified=("weebot/domain/models/plan.py",))
_UNKNOWN = WorkspaceDrift(unavailable_reason="git exploded")


# ── Outcomes ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clean_workspace_passes():
    guard = WorkspaceIntegrityGuard(_StubSnapshots(_CLEAN))

    async with guard.watch() as watch:
        pass

    assert watch.status is VerificationStatus.PASSED
    assert watch.is_clean
    assert watch.violations == []


@pytest.mark.asyncio
async def test_modified_workspace_fails_with_an_integrity_violation():
    guard = WorkspaceIntegrityGuard(_StubSnapshots(_DIRTY))

    async with guard.watch() as watch:
        pass

    assert watch.status is VerificationStatus.FAILED
    assert not watch.is_clean
    assert len(watch.violations) == 1
    violation = watch.violations[0]
    assert violation.dimension is AuditDimension.INTEGRITY
    assert violation.severity is ViolationSeverity.HIGH
    assert "plan.py" in violation.location


@pytest.mark.asyncio
async def test_undetermined_drift_is_not_run_not_passed():
    """The distinction the whole feature turns on (E4 — fail closed)."""
    guard = WorkspaceIntegrityGuard(_StubSnapshots(_UNKNOWN))

    async with guard.watch() as watch:
        pass

    assert watch.status is VerificationStatus.NOT_RUN
    assert not watch.is_clean
    assert watch.violations == [], "an unrunnable check is not evidence of a violation"
    assert "git exploded" in watch.reason


@pytest.mark.asyncio
async def test_unwired_port_is_not_run_and_takes_no_snapshots():
    """Legacy flows built without DI must keep working, but not silently pass."""
    guard = WorkspaceIntegrityGuard(None)

    async with guard.watch() as watch:
        pass

    assert watch.status is VerificationStatus.NOT_RUN
    assert not watch.is_clean
    assert "no workspace snapshot port wired" in watch.reason


# ── The awkward paths ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_guard_still_reports_when_the_block_raises():
    port = _StubSnapshots(_DIRTY)
    guard = WorkspaceIntegrityGuard(port)
    seen: list[IntegrityWatch] = []

    with pytest.raises(RuntimeError):
        async with guard.watch(on_complete=seen.append):
            raise RuntimeError("verification blew up mid-episode")

    assert port.diffs_taken == 1
    assert seen and seen[0].status is VerificationStatus.FAILED


@pytest.mark.asyncio
async def test_on_complete_fires_for_an_early_return():
    """Why on_complete exists: code after the ``async with`` never runs here."""
    port = _StubSnapshots(_DIRTY)
    guard = WorkspaceIntegrityGuard(port)
    seen: list[IntegrityWatch] = []

    async def episode() -> str:
        async with guard.watch(on_complete=seen.append):
            return "bailed out early"

    result = await episode()

    assert result == "bailed out early"
    assert seen and seen[0].status is VerificationStatus.FAILED


@pytest.mark.asyncio
async def test_guard_survives_an_exploding_snapshot_port():
    """A broken guard must not take verification down with it."""

    class _Exploding(WorkspaceSnapshotPort):
        async def snapshot(self):
            raise OSError("disk on fire")

        async def diff(self, before):
            raise AssertionError("should never be reached")

    guard = WorkspaceIntegrityGuard(_Exploding())
    ran = False

    async with guard.watch() as watch:
        ran = True

    assert ran, "the guarded block must still execute"
    assert watch.status is VerificationStatus.NOT_RUN
    assert "baseline snapshot raised" in watch.reason


@pytest.mark.asyncio
async def test_guard_survives_an_exploding_diff():
    class _ExplodingDiff(WorkspaceSnapshotPort):
        async def snapshot(self):
            return WorkspaceSnapshot(backend="stub")

        async def diff(self, before):
            raise OSError("disk on fire")

    guard = WorkspaceIntegrityGuard(_ExplodingDiff())

    async with guard.watch() as watch:
        pass

    assert watch.status is VerificationStatus.NOT_RUN
    assert "drift comparison raised" in watch.reason


def test_guard_is_off_by_default():
    """Default OFF is a cost decision (~3s/episode for ~2000 files), not an
    opinion about whether integrity matters.

    Flipping it should be deliberate, so it fails a test rather than sliding
    in. Turn it on when test_verifier_readonly_tripwire.py starts failing —
    that is the point the guard has something to catch.
    """
    import os

    from weebot.config.feature_flags import WORKSPACE_INTEGRITY_GUARD_ENABLED

    if os.environ.get("WEEBOT_WORKSPACE_INTEGRITY_GUARD"):
        pytest.skip("flag explicitly set in this environment — nothing to assert about the default")

    assert WORKSPACE_INTEGRITY_GUARD_ENABLED is False


@pytest.mark.asyncio
async def test_a_failing_on_complete_does_not_mask_the_block_outcome():
    guard = WorkspaceIntegrityGuard(_StubSnapshots(_CLEAN))

    def _bad_reporter(_watch):
        raise ValueError("reporter is broken")

    async with guard.watch(on_complete=_bad_reporter) as watch:
        pass  # must not raise

    assert watch.status is VerificationStatus.PASSED
