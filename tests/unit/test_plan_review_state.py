"""Tests for Enhancement 4 — PlanReviewState and plan approval flow."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from weebot.application.flows.states.plan_review import (
    PlanReviewState,
    _APPROVE_TOKENS,
    next_state_after_plan,
)
from weebot.domain.models.event import PlanReviewEvent, WaitForUserEvent, ErrorEvent


def _make_plan(steps=3):
    plan = MagicMock()
    plan.title = "Test Plan"
    step_mocks = []
    for i in range(steps):
        s = MagicMock()
        s.id = f"step-{i}"
        s.description = f"Do thing {i}"
        step_mocks.append(s)
    plan.steps = step_mocks
    plan.model_dump = lambda mode=None: {
        "title": "Test Plan",
        "steps": [{"id": s.id, "description": s.description, "status": "pending"} for s in step_mocks],
    }
    return plan


def _make_flow(plan=None):
    flow = MagicMock()
    flow._plan = plan
    ctx = MagicMock()
    ctx.extra = {}
    ctx.get = lambda k, d=None: ctx.extra.get(k, d)
    ctx.model_copy = lambda update=None: MagicMock(extra={**ctx.extra, **(update or {}).get("extra", {})})
    session = MagicMock()
    session.context = ctx
    session.model_copy = lambda update=None: MagicMock(context=update.get("context", ctx) if update else ctx)
    flow._session = session
    # No persistence in these tests — a bare MagicMock() is truthy, which
    # would make PlanReviewState's `if context._state_repo:` guard try to
    # await save_session() on a non-awaitable MagicMock.
    flow._state_repo = None
    return flow


class TestPlanReviewState:
    @pytest.mark.asyncio
    async def test_emits_plan_review_and_wait_for_user(self):
        plan = _make_plan(steps=3)
        flow = _make_flow(plan=plan)

        state = PlanReviewState()
        events = []
        async for event in state.execute(flow, ""):
            events.append(event)

        types = [e.type for e in events]
        assert "plan_review" in types
        assert "wait_for_user" in types

    @pytest.mark.asyncio
    async def test_plan_review_event_has_correct_step_count(self):
        plan = _make_plan(steps=4)
        flow = _make_flow(plan=plan)

        state = PlanReviewState()
        events = []
        async for event in state.execute(flow, ""):
            events.append(event)

        review_events = [e for e in events if e.type == "plan_review"]
        assert len(review_events) == 1
        assert review_events[0].step_count == 4

    @pytest.mark.asyncio
    async def test_no_plan_emits_error_and_falls_through(self):
        flow = _make_flow(plan=None)

        state = PlanReviewState()
        events = []
        async for event in state.execute(flow, ""):
            events.append(event)

        assert any(e.type == "error" for e in events)
        # State was set on the flow
        flow.set_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_approve_below_min_steps(self):
        plan = _make_plan(steps=1)
        flow = _make_flow(plan=plan)

        state = PlanReviewState(min_steps=2)
        events = []
        async for event in state.execute(flow, ""):
            events.append(event)

        # No review event — auto-approved
        assert not any(e.type == "plan_review" for e in events)
        flow.set_state.assert_called_once()


class TestNextStateAfterPlan:
    def test_returns_executing_when_disabled(self):
        from weebot.application.flows.states.executing import ExecutingState
        with patch.dict(os.environ, {"PLAN_REVIEW_ENABLED": "false"}):
            state = next_state_after_plan()
        assert isinstance(state, ExecutingState)

    def test_returns_plan_review_when_enabled(self):
        with patch.dict(os.environ, {"PLAN_REVIEW_ENABLED": "true"}):
            state = next_state_after_plan()
        assert isinstance(state, PlanReviewState)


class TestApproveTokens:
    def test_standard_tokens_present(self):
        for token in ("approve", "yes", "ok", "proceed", "lgtm", "y"):
            assert token in _APPROVE_TOKENS

    def test_non_approval_not_in_tokens(self):
        for non_token in ("no", "cancel", "stop", "modify", "change"):
            assert non_token not in _APPROVE_TOKENS
