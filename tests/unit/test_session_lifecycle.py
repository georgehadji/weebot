"""The session lifecycle is one table (SessionStatus -> allowed SessionAction), and runs settle
on an honest status.

Before, each endpoint wrote its own status check, cancel had none (cancelling a COMPLETED
session saved it as FAILED), and a run cut off by a stuck plan or the iteration limit was left
RUNNING, which the task runner reported as WAITING: a question nobody had asked.
"""

from __future__ import annotations

import time
import types
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from weebot.application.flows.hyper_agent_flow import HyperAgentFlow
from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig, PlanStuckError
from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.event import ErrorEvent
from weebot.domain.models.session import Session, SessionAction, SessionStatus
from weebot.interfaces.web.auth import require_mutation_identity
from weebot.interfaces.web.routers.sessions import router as sessions_router

# --- the table -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "actions"),
    [
        (SessionStatus.PENDING, ["run", "cancel"]),
        (SessionStatus.RUNNING, ["steer", "cancel"]),
        (SessionStatus.WAITING, ["resume", "cancel"]),
        (SessionStatus.COMPLETED, []),
        (SessionStatus.FAILED, ["run"]),
        (SessionStatus.CANCELLED, ["run"]),
    ],
)
def test_each_status_lists_the_actions_it_allows(status, actions):
    assert status.allowed_actions == actions
    for action in SessionAction:
        assert status.allows(action) == (action.value in actions)


# --- cancel ----------------------------------------------------------------------------------


def _app(status: SessionStatus):
    app = FastAPI()
    app.include_router(sessions_router)
    app.dependency_overrides[require_mutation_identity] = lambda: None
    session = Session(id="sess-1", user_id="anonymous", agent_id="weebot-web", status=status)
    saved = {"s": session}
    repo = AsyncMock()
    repo.load_session = AsyncMock(side_effect=lambda _id: saved["s"])
    repo.save_session = AsyncMock(side_effect=lambda s: saved.update(s=s))
    def _set_status(_id, status, expected=None):
        if expected is not None and saved["s"].status not in expected:
            return False
        saved.update(s=saved["s"].set_status(status))
        return True

    repo.update_session_status = AsyncMock(side_effect=_set_status)
    runner = MagicMock()

    async def _cancel(_id):
        # What TaskRunner.cancel_session does for an idle session.
        await repo.update_session_status(_id, SessionStatus.CANCELLED, expected=None)
        return False

    runner.cancel_session = AsyncMock(side_effect=_cancel)

    def _get(port):
        name = getattr(port, "__name__", "")
        if name in ("TaskRunner", "TaskRunnerPort"):
            return runner
        if name == "StateRepositoryPort":
            return repo
        return MagicMock()

    app.state.container = MagicMock(get=MagicMock(side_effect=_get))
    return app, repo, runner


@pytest.mark.parametrize(
    "status", [SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.CANCELLED]
)
def test_cancelling_a_finished_session_changes_nothing(status):
    app, repo, runner = _app(status)
    response = TestClient(app).post("/sessions/sess-1/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == status.value
    runner.cancel_session.assert_not_awaited()
    repo.save_session.assert_not_awaited()


def test_cancelling_a_waiting_session_stops_it():
    app, repo, runner = _app(SessionStatus.WAITING)
    response = TestClient(app).post("/sessions/sess-1/cancel")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["allowed_actions"] == ["run"]
    runner.cancel_session.assert_awaited_once()


def test_cancel_fallback_never_saves_the_stale_snapshot():
    """No TaskRunner, and the run COMPLETED after the route's first load (audit X2)."""
    app, repo, runner = _app(SessionStatus.WAITING)
    runner.cancel_session = AsyncMock(side_effect=RuntimeError("no runner"))
    waiting = Session(
        id="sess-1", user_id="anonymous", agent_id="weebot-web", status=SessionStatus.WAITING
    )
    finished = waiting.set_status(SessionStatus.COMPLETED)

    async def _load(_id, _calls=iter([waiting])):
        return next(_calls, finished)

    repo.load_session = AsyncMock(side_effect=_load)
    response = TestClient(app).post("/sessions/sess-1/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    repo.save_session.assert_not_awaited()
    # The fallback writes only the status, and only while it still allows a cancel.
    expected = repo.update_session_status.await_args.kwargs["expected"]
    assert SessionStatus.COMPLETED not in expected
    assert SessionStatus.WAITING in expected


# --- runs settle on an honest status -------------------------------------------------------


class _LLM:
    async def chat(self, **_):
        return types.SimpleNamespace(content="{}", model="x", usage=None)


class _Spin(FlowState):
    """Never ends and never changes the session status."""

    status = AgentStatus.EXECUTING

    async def execute(self, context, prompt):
        if False:
            yield


class _Stuck(FlowState):
    status = AgentStatus.PLANNING

    async def execute(self, context, prompt):
        context._similar_plan_count = 3  # set by the real similar-plan check before it raises
        raise PlanStuckError("same plan again")
        yield


async def _run_with(state: FlowState) -> tuple[PlanActFlow, list]:
    flow = PlanActFlow(PlanActFlowConfig(
        llm=_LLM(), tools=ToolCollection(), session=Session(id="s1", task="t"), max_iterations=2))
    flow.set_state = lambda _s, _orig=flow.set_state: _orig(state)
    events = [e async for e in flow.run("t")]
    return flow, events


async def test_a_run_out_of_iterations_fails_instead_of_waiting():
    flow, events = await _run_with(_Spin())
    assert flow._session.status == SessionStatus.FAILED
    assert any("Max iterations" in (e.error or "") for e in events if isinstance(e, ErrorEvent))
    assert [e.error_code for e in events if isinstance(e, ErrorEvent)] == ["MAX_ITERATIONS"]


async def test_a_stuck_plan_fails_instead_of_waiting():
    flow, events = await _run_with(_Stuck())
    assert flow._session.status == SessionStatus.FAILED
    assert any("stuck" in (e.error or "") for e in events if isinstance(e, ErrorEvent))
    assert [e.error_code for e in events if isinstance(e, ErrorEvent)] == ["PLAN_STUCK"]


async def test_a_cancel_request_settles_as_cancelled_not_failed(tmp_path, monkeypatch):
    from weebot.core import cancel_requests

    real_time = time.time
    monkeypatch.setattr(cancel_requests, "_DIR", tmp_path)
    # Filed a moment after the run starts: one filed before it is for an earlier run.
    with monkeypatch.context() as m:
        m.setattr(time, "time", lambda: real_time() + 60)
        cancel_requests.request("s1")
    flow, events = await _run_with(_Spin())
    assert flow._session.status == SessionStatus.CANCELLED
    assert [e.error_code for e in events if isinstance(e, ErrorEvent)] == ["CANCELLED"]


async def test_a_failed_swarm_is_not_saved_as_completed():
    flow = HyperAgentFlow(
        llm=MagicMock(), session=Session(id="s1", task="t"), event_bus=AsyncMock(),
        swarm_bus=MagicMock(), sub_agent_factory=MagicMock(), cost_tracker=MagicMock(),
    )
    flow._hyper = MagicMock(execute=AsyncMock(side_effect=RuntimeError("boom")))
    events = [e async for e in flow.run("t")]
    assert isinstance(events[-1], ErrorEvent)
    assert flow._session.status == SessionStatus.FAILED
    assert not flow.is_done()
