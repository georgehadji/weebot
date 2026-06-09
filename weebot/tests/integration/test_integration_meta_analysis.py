"""Integration tests for MetaAnalysisState — HyperAgents Enhancement 1.

Tests the full MetaAnalysisState → CompletedState transition with
mock session data containing real trajectory events.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from weebot.application.flows.states.meta_analysis import MetaAnalysisState
from weebot.domain.models.event import (
    ErrorEvent,
    MessageEvent,
    StepEvent,
    ToolEvent,
    ToolStatus,
)
from weebot.domain.models.plan import Plan, Step, StepStatus as PS
from weebot.domain.models.session import Session, SessionContext, SessionStatus


class TestMetaAnalysisStateIntegration:
    """Integration tests for MetaAnalysisState with real event data."""

    @pytest.fixture
    def mock_flow(self) -> MagicMock:
        """Create a mock PlanActFlow with session, plan, and LLM."""
        flow = MagicMock()
        flow._llm = AsyncMock()
        flow._log = MagicMock()

        # Session with trajectory events
        session = Session(
            id="test-session",
            status=SessionStatus.RUNNING,
            context=SessionContext(
                original_task="Open browser and log into LinkedIn",
                meta_notes=[],
            ),
        )

        # Add trajectory events
        session = session.add_event(
            StepEvent(step_id="step-1", description="Navigate to login", status="completed")
        )
        session = session.add_event(
            ToolEvent(
                tool_call_id="tc1", tool_name="advanced_browser",
                function_name="advanced_browser", function_args={},
                status=ToolStatus.CALLED, result="Navigated to linkedin.com/login",
            )
        )
        session = session.add_event(
            StepEvent(step_id="step-2", description="Wait for page load", status="completed")
        )
        session = session.add_event(
            ToolEvent(
                tool_call_id="tc2", tool_name="advanced_browser",
                function_name="advanced_browser", function_args={},
                status=ToolStatus.CALLED, result="Screenshot captured",
            )
        )
        session = session.add_event(
            ErrorEvent(error="Page.goto: Timeout 30000ms exceeded")
        )
        session = session.add_event(
            StepEvent(step_id="step-3", description="Ask for credentials", status="completed")
        )

        plan = Plan(
            title="Log into LinkedIn",
            message="Navigate to LinkedIn and log in",
            steps=[
                Step(id="step-1", description="Navigate to login", status="completed"),
                Step(id="step-2", description="Wait for page load", status="completed"),
                Step(id="step-3", description="Ask for credentials", status="completed"),
            ],
        )

        flow._session = session
        flow._plan = plan
        return flow

    @pytest.mark.asyncio
    async def test_meta_analysis_produces_note(self, mock_flow: MagicMock) -> None:
        """MetaAnalysisState should produce a meta-note from trajectory data."""
        mock_flow._llm.chat.return_value = MagicMock(
            content='{"what_worked":["Navigation succeeded"],"what_failed":["Timeout on goto"],"strategy_change":"Use domcontentloaded instead of networkidle"}'
        )

        state = MetaAnalysisState()
        await state.execute(mock_flow, "")

        # Should have added a meta-note
        assert len(mock_flow._session.context.meta_notes) > 0
        assert "domcontentloaded" in mock_flow._session.context.meta_notes[0]
        assert "Timeout" in mock_flow._session.context.meta_notes[0]

    @pytest.mark.asyncio
    async def test_meta_analysis_transitions_to_completed(self, mock_flow: MagicMock) -> None:
        """After execution, the state should transition to CompletedState."""
        mock_flow._llm.chat.return_value = MagicMock(
            content='{"what_worked":[],"what_failed":[],"strategy_change":""}'
        )

        state = MetaAnalysisState()
        await state.execute(mock_flow, "")

        # Should have called set_state
        mock_flow.set_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_meta_analysis_survives_llm_failure(self, mock_flow: MagicMock) -> None:
        """If the LLM call fails, the state should still transition to CompletedState."""
        mock_flow._llm.chat.side_effect = RuntimeError("LLM unavailable")

        state = MetaAnalysisState()
        await state.execute(mock_flow, "")

        # Should still transition to completed
        mock_flow.set_state.assert_called_once()
        # No meta-notes should have been added
        assert mock_flow._session.context.meta_notes == []

    @pytest.mark.asyncio
    async def test_empty_session_no_crash(self) -> None:
        """State with empty session should not crash."""
        flow = MagicMock()
        flow._llm = AsyncMock()
        flow._log = MagicMock()
        flow._session = Session(id="empty", context=SessionContext())
        flow._plan = Plan(title="Empty", message="", steps=[])
        flow._llm.chat.return_value = MagicMock(
            content='{"what_worked":[],"what_failed":[],"strategy_change":""}'
        )

        state = MetaAnalysisState()
        await state.execute(flow, "")
        flow.set_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_plan_no_crash(self) -> None:
        """State with None plan should not crash."""
        flow = MagicMock()
        flow._llm = AsyncMock()
        flow._log = MagicMock()
        flow._session = Session(id="test", context=SessionContext())
        flow._plan = None
        flow._llm.chat.return_value = MagicMock(
            content='{"what_worked":[],"what_failed":[],"strategy_change":""}'
        )

        state = MetaAnalysisState()
        await state.execute(flow, "")
        flow.set_state.assert_called_once()
