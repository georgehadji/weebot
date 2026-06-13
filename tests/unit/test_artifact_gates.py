"""Tests for Enhancement 3 — artifact-based completion gates in VerifyingState."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.application.flows.states.verifying import VerifyingState
from weebot.domain.models.event import ToolEvent, ToolStatus, VerificationEvent


def _make_flow(events=None):
    """Build a minimal mock flow with the given session events."""
    flow = MagicMock()
    flow._plan = MagicMock()
    flow._plan.steps = []
    session = MagicMock()
    session.events = events or []
    flow._session = session
    flow._executor = None
    return flow


def _tool_event(tool_name, function_args, result="", status=ToolStatus.CALLED):
    return ToolEvent(
        tool_name=tool_name,
        function_name=tool_name,
        function_args=function_args,
        status=status,
        result=result,
    )


class TestArtifactVerificationGate:
    @pytest.mark.asyncio
    async def test_existing_file_passes(self, tmp_path):
        target = tmp_path / "test.py"
        target.write_text("print('hello')")
        flow = _make_flow([
            _tool_event("file_editor", {"path": str(target)})
        ])
        state = VerifyingState()
        failures = await state._gate_artifact_verification(flow)
        assert failures == []

    @pytest.mark.asyncio
    async def test_missing_file_flagged(self):
        flow = _make_flow([
            _tool_event("file_editor", {"path": "/nonexistent/__missing_file__.py"})
        ])
        state = VerifyingState()
        failures = await state._gate_artifact_verification(flow)
        assert any("written_files_missing" in f for f in failures)

    @pytest.mark.asyncio
    async def test_failed_pytest_output_flagged(self):
        flow = _make_flow([
            _tool_event(
                "bash",
                {"command": "pytest tests/"},
                result="FAILED tests/test_foo.py::test_bar - AssertionError",
            )
        ])
        state = VerifyingState()
        failures = await state._gate_artifact_verification(flow)
        assert "test_run_failed" in failures

    @pytest.mark.asyncio
    async def test_passing_tests_not_flagged(self):
        flow = _make_flow([
            _tool_event(
                "bash",
                {"command": "pytest tests/"},
                result="5 passed in 1.23s",
            )
        ])
        state = VerifyingState()
        failures = await state._gate_artifact_verification(flow)
        assert "test_run_failed" not in failures

    @pytest.mark.asyncio
    async def test_no_tool_events_passes(self):
        flow = _make_flow([])
        state = VerifyingState()
        failures = await state._gate_artifact_verification(flow)
        assert failures == []

    @pytest.mark.asyncio
    async def test_invalid_path_does_not_raise(self):
        flow = _make_flow([
            _tool_event("file_editor", {"path": ":::invalid:::"})
        ])
        state = VerifyingState()
        # Should not raise
        failures = await state._gate_artifact_verification(flow)
        assert isinstance(failures, list)

    @pytest.mark.asyncio
    async def test_non_test_bash_not_flagged(self):
        flow = _make_flow([
            _tool_event("bash", {"command": "echo hello"}, result="failed output")
        ])
        state = VerifyingState()
        failures = await state._gate_artifact_verification(flow)
        assert "test_run_failed" not in failures
