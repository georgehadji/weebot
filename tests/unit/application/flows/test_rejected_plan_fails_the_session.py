"""A rejected plan (402 no credits, bad key) must end the session, not re-enter planning.

Seen live: OpenRouter answered 402, PlanningState yielded an error and returned with the session
still RUNNING, so the flow loop re-entered it at once -- 47+ identical errors, a session stuck.
"""

from __future__ import annotations

from types import SimpleNamespace

from weebot.application.flows.states.planning import PlanningState
from weebot.domain.models.session import Session, SessionStatus


class _RejectingMediator:
    def __init__(self):
        self.calls = 0

    async def send(self, command):
        self.calls += 1
        return SimpleNamespace(success=False, error="Error code: 402 - Insufficient credits", data={})


async def test_rejection_marks_the_session_failed_so_the_loop_stops():
    session = Session(id="s", user_id="u", agent_id="a").set_status(SessionStatus.RUNNING)
    mediator = _RejectingMediator()
    context = SimpleNamespace(
        _session=session,
        _mediator=mediator,
        _llm=None,
        _model=None,
        _misalignment_journal=None,
        _maybe_switch_model_for_context=lambda: None,
    )

    events = [e async for e in PlanningState().execute(context, "yes")]

    assert [e.type for e in events] == ["error"]
    assert "Insufficient credits" in events[0].error
    assert context._session.status == SessionStatus.FAILED  # PlanActFlow.run breaks on FAILED
    assert mediator.calls == 1
