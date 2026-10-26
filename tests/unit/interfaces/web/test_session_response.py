"""The sessions router turns a Session into SessionResponse (found in plan B2c).

`POST /api/sessions` returned 500 for every new session from the web UI:
`_session_to_response` passed the `SessionContext` model where
`SessionResponse.context` is a dict. `GET /api/sessions` hits the same code
for every listed session, so it fails as soon as one session exists.
"""

from __future__ import annotations

from weebot.domain.models.session import Session
from weebot.interfaces.web.routers.sessions import _session_to_response


def test_a_session_with_context_converts():
    session = Session(id="s1", user_id="u", agent_id="a", context={"last_prompt": "hi"})
    response = _session_to_response(session)
    assert response.id == "s1"
    assert isinstance(response.context, dict)
    assert "hi" in str(response.context)


# --- Phase 2 of tasks/specs/ui_ux_remediation_plan.md: title and event count ---------------


def test_a_session_without_a_title_shows_one_derived_from_its_prompt():
    session = Session(
        id="s2", user_id="u", agent_id="a", context={"last_prompt": "# Summarise the **Q3** report"}
    )
    assert _session_to_response(session).title == "Summarise the Q3 report"


def test_original_task_beats_a_short_follow_up_prompt():
    session = Session(
        id="s3",
        user_id="u",
        agent_id="a",
        context={"_original_task": "Plan the launch", "last_prompt": "yes"},
    )
    assert _session_to_response(session).title == "Plan the launch"


def test_a_stored_title_wins_and_no_prompt_means_no_title():
    stored = Session(id="s4", user_id="u", agent_id="a", title="Mine", context={"last_prompt": "x"})
    assert _session_to_response(stored).title == "Mine"
    assert _session_to_response(Session(id="s5", user_id="u", agent_id="a")).title is None


def test_event_count_is_the_one_passed_in_not_the_empty_session_list():
    session = Session(id="s6", user_id="u", agent_id="a")
    assert _session_to_response(session).event_count == 0
    assert _session_to_response(session, 42).event_count == 42


def test_the_list_route_asks_the_store_once_for_every_session():
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from weebot.application.ports.event_store_port import EventStorePort
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.interfaces.web.routers.sessions import router

    sessions = [
        Session(id="a", user_id="anonymous", agent_id="w", context={"last_prompt": "first job"}),
        Session(id="b", user_id="anonymous", agent_id="w", title="Named"),
    ]
    repo = AsyncMock()
    repo.list_sessions = AsyncMock(return_value=sessions)
    repo.count_sessions = AsyncMock(return_value=2)
    store = MagicMock()
    store.count_events = AsyncMock(return_value={"a": 7, "b": 0})
    container = MagicMock()
    container.get = MagicMock(
        side_effect=lambda port: {StateRepositoryPort: repo, EventStorePort: store}[port]
    )
    app = FastAPI()
    app.include_router(router)
    app.state.container = container

    body = TestClient(app).get("/sessions").json()

    store.count_events.assert_awaited_once_with(["a", "b"])
    assert [(s["id"], s["title"], s["event_count"]) for s in body["sessions"]] == [
        ("a", "first job", 7),
        ("b", "Named", 0),
    ]
