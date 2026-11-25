"""`flow cancel` stops a run in another process (F77).

The CLI command reached only TaskRunner tasks in its own process, so a
`flow run` in another terminal could not be cancelled. A cancel request is now
a marker file the flow checks on every iteration.
"""

from __future__ import annotations

import time
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


def _request_during_the_run(monkeypatch, session_id):
    """File a cancel as if a moment after the run started (the flow starts its clock later)."""
    real = time.time
    with monkeypatch.context() as m:
        m.setattr(time, "time", lambda: real() + 60)
        cancel_requests.request(session_id)


def test_a_request_older_than_the_run_is_consumed_but_ignored(tmp_path, monkeypatch):
    """`flow cancel` on a WAITING session files a marker nobody reads; the next run must not
    stop on it (audit X3)."""
    monkeypatch.setattr(cancel_requests, "_DIR", tmp_path)
    cancel_requests.request("s1")
    assert not cancel_requests.take("s1", since=time.time() + 1)
    assert not cancel_requests.take("s1")  # consumed all the same


def test_a_request_after_the_run_started_is_seen(tmp_path, monkeypatch):
    monkeypatch.setattr(cancel_requests, "_DIR", tmp_path)
    started = time.time()
    cancel_requests.request("s1")
    assert cancel_requests.take("s1", since=started)


def test_a_marker_in_the_old_format_is_ignored_by_a_run(tmp_path, monkeypatch):
    monkeypatch.setattr(cancel_requests, "_DIR", tmp_path)
    cancel_requests._marker("s1").parent.mkdir(parents=True, exist_ok=True)
    cancel_requests._marker("s1").write_text("s1", encoding="utf-8")
    assert not cancel_requests.take("s1", since=time.time())


async def test_a_flow_ignores_a_cancel_filed_before_it_started(tmp_path, monkeypatch):
    from weebot.application.flows.plan_act_flow import PlanActFlow
    from weebot.application.models.tool_collection import ToolCollection

    monkeypatch.setattr(cancel_requests, "_DIR", tmp_path)
    session = Session(id="run-2", task="t")
    flow = PlanActFlow(llm=MagicMock(), tools=ToolCollection(), session=session)
    cancel_requests.request("run-2")
    events = []
    try:
        async for event in flow.run("do it"):
            events.append(event)
            break  # one event is enough: the first iteration has already checked the marker
    finally:
        await flow.teardown()
    assert not any(getattr(e, "error_code", None) == "CANCELLED" for e in events)
    assert flow._session.status != SessionStatus.CANCELLED
    assert not cancel_requests.take("run-2")  # consumed


async def test_a_running_flow_stops_on_request(tmp_path, monkeypatch):
    from weebot.application.flows.plan_act_flow import PlanActFlow
    from weebot.application.models.tool_collection import ToolCollection

    monkeypatch.setattr(cancel_requests, "_DIR", tmp_path)
    session = Session(id="run-1", task="t")
    flow = PlanActFlow(llm=MagicMock(), tools=ToolCollection(), session=session)
    _request_during_the_run(monkeypatch, "run-1")
    events = [e async for e in flow.run("do it")]
    assert any(isinstance(e, ErrorEvent) and "ancel" in e.error for e in events)
    assert flow._session.status == SessionStatus.CANCELLED
