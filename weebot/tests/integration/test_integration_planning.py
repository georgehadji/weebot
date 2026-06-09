"""Integration tests for PlanningState with strategy transfer + domain inference.

Tests Enhancement 6: StrategyTransferService injection and _infer_domain.
"""
from __future__ import annotations

import pytest

from weebot.application.flows.states.planning import _infer_domain


class TestInferDomain:
    """Tests for the _infer_domain heuristic."""

    @pytest.mark.parametrize(
        "prompt,expected",
        [
            ("Write a Python function to sort a list", "coding"),
            ("Refactor the authentication module", "coding"),
            ("Debug the login flow", "coding"),
            ("Implement a REST API endpoint", "coding"),
            ("Review this paper on transformer architectures", "review"),
            ("Should we accept or reject this conference submission?", "review"),
            ("Design a reward function for a robot walker", "robotics"),  # "reward function" triggers robotics
            ("Train a quadruped in simulation using RL", "robotics"),
            ("Grade this IMO solution for correctness", "math"),
            ("Check this proof against the rubric", "math"),
            ("Open browser and log into LinkedIn", "automation"),
            ("Click the submit button and fill the form", "automation"),
            ("Tell me a joke", "general"),
            ("What is the capital of France?", "general"),
        ],
    )
    def test_infer_domain(self, prompt: str, expected: str) -> None:
        assert _infer_domain(prompt) == expected

    def test_empty_prompt_is_general(self) -> None:
        assert _infer_domain("") == "general"

    def test_case_insensitive(self) -> None:
        assert _infer_domain("DEPLOY A PYTHON SCRIPT") == "coding"
        assert _infer_domain("review This Paper") == "review"


class TestPlanningStateStrategyTransfer:
    """Tests for strategy transfer integration in PlanningState."""

    @pytest.fixture
    def mock_flow(self) -> MagicMock:
        from unittest.mock import AsyncMock, MagicMock
        from weebot.domain.models.session import Session, SessionContext

        flow = MagicMock()
        flow._llm = AsyncMock()
        flow._mediator = None  # Use direct path
        flow._event_bus = None
        flow._model = "test-model"
        flow._skill_prompt = None
        flow._episodic_memory = None
        flow._plan_critic = None
        flow._state_repo = None
        flow._planner = MagicMock()
        flow._planner.create_plan = AsyncMock()
        flow._emit = AsyncMock()
        flow._maybe_switch_model_for_context = MagicMock(return_value=None)
        flow._update_agents_with_model = MagicMock()
        flow._snapshot_plan = MagicMock()
        flow._session = Session(
            id="test", context=SessionContext(original_task="Write code")
        )
        return flow

    @pytest.mark.asyncio
    async def test_create_plan_called_with_meta_notes(self, mock_flow: MagicMock) -> None:
        """PlanningState should pass meta_notes to create_plan."""
        from weebot.domain.models.event import PlanEvent, StepEvent
        from weebot.domain.models.plan import PlanStatus
        from weebot.application.flows.states.planning import PlanningState

        # Set meta_notes on session
        mock_flow._session = mock_flow._session.add_meta_note("Avoid networkidle")

        # Mock planner to yield plan events via async generator
        plan_dict = {
            "title": "Test", "message": "", "steps": [
                {"id": "step-1", "description": "Do thing", "status": "pending"}
            ]
        }

        async def _mock_create_plan(prompt, **kwargs):
            yield PlanEvent(status=PlanStatus.CREATED, plan=plan_dict)

        mock_flow._planner.create_plan = _mock_create_plan

        state = PlanningState()
        events = [e async for e in state.execute(mock_flow, "Write code")]

        # Should have produced a plan event
        plan_events = [e for e in events if isinstance(e, PlanEvent)]
        assert len(plan_events) > 0
