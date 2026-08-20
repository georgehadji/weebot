"""Behavioural tests for StepEvidenceAuditor, testing the auditor directly
against a real LocalFileStorageAdapter rather than through VerifyingState.

Finding A of tasks/specs/test_suite_and_evidence_gate_repair_plan.md: Gate A
(written-files-exist) silently returned [] whenever the audited path fell
outside the storage adapter's root — indistinguishable from "all files
verified present." This file's tests fail on the pre-fix code (A1 unbound
root_dir="."; A3 swallowed ValueError as a debug-logged skip) and pass after.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from weebot.domain.models.audit import AuditDimension, AuditVerdict, ViolationSeverity
from weebot.domain.models.event import ToolEvent
from weebot.infrastructure.adapters.file_storage_adapter import LocalFileStorageAdapter
from weebot.application.services.step_evidence_auditor import StepEvidenceAuditor


def _write_event(path: str) -> ToolEvent:
    return ToolEvent(tool_name="file_editor", function_args={"path": path}, result="ok")


@pytest.mark.asyncio
async def test_out_of_root_write_is_flagged_not_silently_skipped(tmp_path: Path) -> None:
    """A written path outside the storage root must not report a clean bill of health.

    Regresses Finding A: the old code caught the resulting ValueError,
    logged at debug, and `continue`d — the gate returned [] as if the file
    had been verified present.
    """
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    outside_root = tmp_path / "elsewhere"
    outside_root.mkdir()
    (outside_root / "report.txt").write_text("real file, wrong root")

    auditor = StepEvidenceAuditor(file_storage=LocalFileStorageAdapter(root_dir=storage_root))
    report = await auditor.audit_step(step=None, events=[_write_event("../elsewhere/report.txt")])

    assert report.violations, "out-of-root path must produce a violation, not an empty list"
    assert report.verdict != AuditVerdict.PASS
    v = report.violations[0]
    assert v.dimension == AuditDimension.INTEGRITY
    assert v.severity == ViolationSeverity.MEDIUM


@pytest.mark.asyncio
async def test_missing_file_inside_root_is_still_flagged(tmp_path: Path) -> None:
    """Sanity check: Gate A still catches a genuinely missing file inside the root."""
    auditor = StepEvidenceAuditor(file_storage=LocalFileStorageAdapter(root_dir=tmp_path))
    report = await auditor.audit_step(step=None, events=[_write_event("never_written.txt")])

    assert report.violations
    assert report.violations[0].dimension == AuditDimension.COMPLETENESS
    assert "missing on disk" in report.violations[0].description


@pytest.mark.asyncio
async def test_file_present_inside_root_passes(tmp_path: Path) -> None:
    (tmp_path / "written.txt").write_text("here")
    auditor = StepEvidenceAuditor(file_storage=LocalFileStorageAdapter(root_dir=tmp_path))
    report = await auditor.audit_step(step=None, events=[_write_event("written.txt")])

    assert report.verdict == AuditVerdict.PASS
    assert not report.violations
