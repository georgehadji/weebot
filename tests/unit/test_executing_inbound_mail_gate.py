"""Tests for the inbound-mail approval gate in ExecutingState (ADR 006 / R1).

Covers both sides of the gate:
  - WRITE side: _step_fetched_inbound_mail() detection of a completed
    atomic_mail jmap_request event.
  - READ side: ExecutingState.execute() pauses with a WaitForUserEvent when the
    session carries the atomic_mail_inbound_pending flag, and clears the flag so
    a subsequent resume proceeds.

These exercise security-relevant code: inbound email is untrusted input and must
not be acted on without explicit user approval.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from weebot.application.flows.states.executing import (
    ExecutingState,
    _step_fetched_inbound_mail,
)
from weebot.domain.models.event import (
    MessageEvent,
    ToolEvent,
    ToolStatus,
    WaitForUserEvent,
)
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session, SessionStatus


# ---------------------------------------------------------------------------
# WRITE side — _step_fetched_inbound_mail detection predicate
# ---------------------------------------------------------------------------


def _jmap_event(args: dict | None = None) -> ToolEvent:
    return ToolEvent(
        tool_name="atomic_mail",
        status=ToolStatus.CALLED,
        function_args=args if args is not None else {},
        result='{"methodResponses": []}',
    )


def test_detects_completed_jmap_request_with_explicit_action():
    events = [_jmap_event({"action": "jmap_request", "ops_file": "list_inbox"})]
    assert _step_fetched_inbound_mail(events) is True


def test_detects_jmap_when_args_empty():
    # Serialized events may not carry function_args; treat atomic_mail-called as inbound.
    assert _step_fetched_inbound_mail([_jmap_event({})]) is True


def test_register_action_is_not_gated():
    events = [_jmap_event({"action": "register", "username": "bot"})]
    assert _step_fetched_inbound_mail(events) is False


def test_help_action_is_not_gated():
    events = [_jmap_event({"action": "help"})]
    assert _step_fetched_inbound_mail(events) is False


def test_calling_status_is_not_yet_complete():
    calling = ToolEvent(
        tool_name="atomic_mail",
        status=ToolStatus.CALLING,
        function_args={"action": "jmap_request"},
    )
    assert _step_fetched_inbound_mail([calling]) is False


def test_other_tools_are_ignored():
    other = ToolEvent(tool_name="bash", status=ToolStatus.CALLED, function_args={})
    assert _step_fetched_inbound_mail([other, MessageEvent(message="hi")]) is False


def test_empty_events_returns_false():
    assert _step_fetched_inbound_mail([]) is False


# ---------------------------------------------------------------------------
# READ side — ExecutingState pauses for approval when flag is set
# ---------------------------------------------------------------------------


def _make_context(session: Session, plan: Plan) -> SimpleNamespace:
    """Context for driving ExecutingState through the gate.

    When the gate fires it returns before any of the auxiliary collaborators are
    touched. When it does NOT fire, execution proceeds to the mediator-None
    guard (yielding an ErrorEvent) — so the absence of a WaitForUserEvent proves
    the gate stayed silent. All collaborators below are set to inert defaults to
    let that path run without external services.
    """
    state_calls: list = []
    return SimpleNamespace(
        _session=session,
        _plan=plan,
        _mediator=None,  # forces an early ErrorEvent bail after the gate
        _behavioral_learner=None,
        _steering=None,
        _hooks=None,
        _task_preset=None,
        _step_execution_counts={},
        _max_step_repetitions=10,
        set_state=lambda s: state_calls.append(s),
        _state_calls=state_calls,
    )


@pytest.mark.asyncio
async def test_gate_pauses_when_inbound_pending(monkeypatch):
    """A session flagged with inbound mail pending pauses for user approval."""
    monkeypatch.setenv("CONSTRAINT_CHECK_ENABLED", "false")
    session = Session().set_fact("atomic_mail_inbound_pending", True)
    plan = Plan(title="t", steps=[Step(id="s2", description="summarise the email")])
    ctx = _make_context(session, plan)

    events = [e async for e in ExecutingState().execute(ctx, "go")]

    pauses = [e for e in events if isinstance(e, WaitForUserEvent)]
    assert len(pauses) == 1
    assert "untrusted input" in pauses[0].question
    # Session moved to WAITING and the flag was cleared so resume proceeds.
    assert ctx._session.status == SessionStatus.WAITING
    assert ctx._session.get_fact("atomic_mail_inbound_pending") is False


@pytest.mark.asyncio
async def test_gate_does_not_pause_when_flag_absent(monkeypatch):
    """Without the flag, the gate is skipped (flow proceeds to the mediator check)."""
    monkeypatch.setenv("CONSTRAINT_CHECK_ENABLED", "false")
    session = Session()  # no inbound flag
    plan = Plan(title="t", steps=[Step(id="s1", description="do work")])
    ctx = _make_context(session, plan)

    events = [e async for e in ExecutingState().execute(ctx, "go")]

    # No approval pause; the gate did not fire.
    assert not any(isinstance(e, WaitForUserEvent) for e in events)


@pytest.mark.asyncio
async def test_gate_clears_flag_so_resume_does_not_reprompt(monkeypatch):
    """After a pause, re-entering execute() with the cleared flag does not re-pause."""
    monkeypatch.setenv("CONSTRAINT_CHECK_ENABLED", "false")
    session = Session().set_fact("atomic_mail_inbound_pending", True)
    plan = Plan(title="t", steps=[Step(id="s2", description="summarise the email")])
    ctx = _make_context(session, plan)

    # First pass: pauses.
    first = [e async for e in ExecutingState().execute(ctx, "go")]
    assert any(isinstance(e, WaitForUserEvent) for e in first)

    # Second pass (simulated resume): flag is cleared, so no second pause.
    second = [e async for e in ExecutingState().execute(ctx, "proceed")]
    assert not any(isinstance(e, WaitForUserEvent) for e in second)
