"""`flow cancel` stops a run in another process (F77).

The CLI command reached only TaskRunner tasks in its own process, so a
`flow run` in another terminal could not be cancelled. A cancel request is now
a marker file the flow checks on every iteration.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from weebot.core import cancel_requests
from weebot.domain.models.event import ErrorEvent
from weebot.domain.models.session import Session, SessionStatus


def test_a_request_is_seen_once(tmp_path, monkeypatch):
    monkeypatch.setattr(cancel_requests, "_DIR", tmp_path)
    assert not cancel_requests.take("s1")
    cancel_requests.request("s1")
    assert cancel_requests.take("s1")
    assert not cancel_requests.take("s1")  # consumed


def test_odd_session_ids_cannot_escape_the_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(cancel_requests, "_DIR", tmp_path / "cancel")
    cancel_requests.request("../../evil")
    assert not (tmp_path / "evil").exists()
    assert cancel_requests.take("../../evil")


async def test_a_running_flow_stops_on_request(tmp_path, monkeypatch):
    from weebot.application.flows.plan_act_flow import PlanActFlow
    from weebot.application.models.tool_collection import ToolCollection

    monkeypatch.setattr(cancel_requests, "_DIR", tmp_path)
    flow = PlanActFlow(llm=MagicMock(), tools=ToolCollection(), session=Session(id="run-1", task="t"))
    cancel_requests.request("run-1")
    events = [e async for e in flow.run("do it")]
    assert any(isinstance(e, ErrorEvent) and "ancel" in e.error for e in events)
    assert flow._session.status == SessionStatus.FAILED
