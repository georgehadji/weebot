"""Tests for Enhancement 3 — artifact-based completion gates.

Finding C of tasks/specs/test_suite_and_evidence_gate_repair_plan.md: this
file predated commit 8cc7611, which rewrote
VerifyingState._gate_artifact_verification into pure delegation to
StepEvidenceAuditor. The five behaviour cases now live at that layer (C1),
tested against a real LocalFileStorageAdapter per §A. VerifyingState itself
gets one delegation test (C2): does it call the service and format its
violations, not whether the gates fire.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.application.flows.states.verifying import VerifyingState
from weebot.application.services.step_evidence_auditor import StepEvidenceAuditor
from weebot.domain.models.audit import (
    AuditDimension,
    AuditReport,
    AuditVerdict,
    Violation,
    ViolationSeverity,
)
from weebot.domain.models.event import ToolEvent
from weebot.domain.models.plan import Plan, Step, StepStatus
from weebot.domain.models.session import Session
from weebot.infrastructure.adapters.file_storage_adapter import LocalFileStorageAdapter


def _flow_with_completed_step() -> MagicMock:
    """Copied from test_verifying_fail_closed.py:37-48 — same private-helper
    convention (two call sites, not yet a shared fixture)."""
    flow = MagicMock()
    flow._verifier_llm = None
    flow._step_audit_service = None
    flow._workspace_snapshots = None
    flow._hooks = None  # MagicMock's auto-attr would be truthy + non-awaitable
    flow._session = Session()
    step = Step(description="do thing", status=StepStatus.COMPLETED, result="did thing")
    flow._plan = Plan(goal="g", steps=[step])
    flow._states: list = []
    flow.set_state = lambda s: flow._states.append(s)
    return flow


def _tool_event(tool_name, function_args, result=""):
    return ToolEvent(tool_name=tool_name, function_args=function_args, result=result)


class TestStepEvidenceAuditorArtifactGates:
    """C1: the five behaviours, tested directly against StepEvidenceAuditor."""

    @pytest.mark.asyncio
    async def test_existing_file_passes(self, tmp_path):
        (tmp_path / "test.py").write_text("print('hello')")
        auditor = StepEvidenceAuditor(file_storage=LocalFileStorageAdapter(root_dir=tmp_path))

        report = await auditor.audit_step(
            step=None, events=[_tool_event("file_editor", {"path": "test.py"})]
        )

        assert report.violations == []
        assert report.verdict == AuditVerdict.PASS

    @pytest.mark.asyncio
    async def test_missing_file_flagged(self, tmp_path):
        auditor = StepEvidenceAuditor(file_storage=LocalFileStorageAdapter(root_dir=tmp_path))

        report = await auditor.audit_step(
            step=None, events=[_tool_event("file_editor", {"path": "__missing_file__.py"})]
        )

        assert report.violations
        v = report.violations[0]
        assert v.dimension == AuditDimension.COMPLETENESS
        assert "missing on disk" in v.description

    @pytest.mark.asyncio
    async def test_failed_pytest_output_flagged(self, tmp_path):
        auditor = StepEvidenceAuditor(file_storage=LocalFileStorageAdapter(root_dir=tmp_path))

        report = await auditor.audit_step(
            step=None,
            events=[
                _tool_event(
                    "bash",
                    {"command": "pytest tests/"},
                    result="FAILED tests/test_foo.py::test_bar - AssertionError\n1 failed",
                )
            ],
        )

        assert report.violations
        v = report.violations[0]
        assert v.dimension == AuditDimension.ACCURACY
        assert "test run reported failure" in v.description

    @pytest.mark.asyncio
    async def test_passing_tests_not_flagged(self, tmp_path):
        auditor = StepEvidenceAuditor(file_storage=LocalFileStorageAdapter(root_dir=tmp_path))

        report = await auditor.audit_step(
            step=None,
            events=[
                _tool_event("bash", {"command": "pytest tests/"}, result="5 passed, 0 failed in 1.23s")
            ],
        )

        assert report.violations == []

    @pytest.mark.asyncio
    async def test_non_test_bash_not_flagged(self, tmp_path):
        auditor = StepEvidenceAuditor(file_storage=LocalFileStorageAdapter(root_dir=tmp_path))

        report = await auditor.audit_step(
            step=None, events=[_tool_event("bash", {"command": "echo hello"}, result="failed output")]
        )

        assert report.violations == []

    @pytest.mark.asyncio
    async def test_invalid_path_does_not_raise(self, tmp_path):
        auditor = StepEvidenceAuditor(file_storage=LocalFileStorageAdapter(root_dir=tmp_path))

        report = await auditor.audit_step(
            step=None, events=[_tool_event("file_editor", {"path": "bad\x00path.py"})]
        )

        assert isinstance(report.violations, list)


class TestVerifyingStateArtifactGateDelegation:
    """C2: VerifyingState._gate_artifact_verification only needs to prove it
    delegates — the gate behaviours themselves are §C1's job now."""

    @pytest.mark.asyncio
    async def test_no_audit_service_wired_skips_gate(self):
        flow = _flow_with_completed_step()

        failures = await VerifyingState()._gate_artifact_verification(flow)

        assert failures == []

    @pytest.mark.asyncio
    async def test_violations_are_formatted_as_dimension_description(self):
        flow = _flow_with_completed_step()
        flow._step_audit_service = MagicMock()
        flow._step_audit_service.audit_step = AsyncMock(
            return_value=AuditReport(
                session_id=flow._session.id,
                verdict=AuditVerdict.CONDITIONAL,
                violations=[
                    Violation(
                        dimension=AuditDimension.COMPLETENESS,
                        severity=ViolationSeverity.HIGH,
                        description="written file missing on disk: out.py",
                        location="out.py",
                        recommendation="rewrite it",
                    )
                ],
                summary="written file missing on disk: out.py",
                score=0.5,
            )
        )

        failures = await VerifyingState()._gate_artifact_verification(flow)

        assert failures == ["completeness:written file missing on disk: out.py"]
