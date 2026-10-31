"""F2 / decision D-BEH (2026-10-31): the behavior panel shows each principal its own sessions.

Any authenticated caller could read any session's behavior data, stop another session's
tracker, and start a watcher on any directory on the host (the path was echoed back). Now
the session routes check ownership, recent actions drop other principals' sessions, and
``watch/start`` accepts only a directory inside the workspace. ``/trust`` and ``/report``
stay global: they are aggregates.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.core.behavior_reporting import LedgerEntry
# `from ...routers import behavior_router` yields the APIRouter, not the module.
br = importlib.import_module("weebot.interfaces.web.routers.behavior_router")

OWNERS = {"mine": "anonymous", "theirs": "alice"}


class _Repo:
    async def load_session(self, session_id):
        owner = OWNERS.get(session_id)
        return SimpleNamespace(user_id=owner) if owner else None


class _Container:
    def get(self, port):
        assert port is StateRepositoryPort
        return _Repo()


def _entry(session_id: str) -> LedgerEntry:
    return LedgerEntry(
        timestamp=f"2026-10-31T00:00:0{len(session_id)}", date="2026-10-31", action="created",
        path=f"/x/{session_id}.txt", initiated="autonomous", session_id=session_id,
        agent_version="v",
    )


@pytest.fixture
def client(monkeypatch, tmp_path):
    from weebot.config import settings as mod

    monkeypatch.setattr(mod.get_settings(), "weebot_api_key", None, raising=False)
    monkeypatch.setenv("WEEBOT_ENFORCE_SESSION_OWNERSHIP", "true")
    monkeypatch.setattr(br, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(
        br.reporter, "get_recent_actions",
        lambda count=10, session_id=None: [
            e for e in (_entry("mine"), _entry("theirs")) if session_id in (None, e.session_id)
        ][:count],
    )
    monkeypatch.setattr(br.reporter, "get_session_summary", lambda sid: {
        "session_id": sid, "total_actions": 1, "actions_by_type": {}, "start_time": None,
        "end_time": None,
    })
    app = FastAPI()
    app.state.container = _Container()
    app.include_router(br.router)
    return TestClient(app, client=("127.0.0.1", 50000))  # loopback: may mutate, no key set


@pytest.mark.parametrize("method,path", [
    ("get", "/behavior/session/theirs"),
    ("get", "/behavior/watch/status?session_id=theirs"),
    ("post", "/behavior/watch/stop?session_id=theirs"),
    ("get", "/behavior/recent?session_id=theirs"),
])
def test_another_principals_session_is_not_found(client, method, path):
    assert getattr(client, method)(path).status_code == 404


def test_my_session_is_readable(client):
    assert client.get("/behavior/session/mine").json()["session_id"] == "mine"
    assert client.get("/behavior/watch/status?session_id=mine").status_code == 200


def test_recent_without_a_session_drops_other_principals(client):
    assert [e["session_id"] for e in client.get("/behavior/recent").json()] == ["mine"]


def test_watching_outside_the_workspace_is_refused_without_echoing_the_path(client, tmp_path):
    outside = tmp_path.parent
    reply = client.post(f"/behavior/watch/start?session_id=mine&directory={outside}")
    assert reply.status_code == 400
    assert str(outside) not in reply.text


def test_watching_a_missing_directory_does_not_echo_it(client, tmp_path):
    missing = tmp_path / "nope-secret-name"
    reply = client.post(f"/behavior/watch/start?session_id=mine&directory={missing}")
    assert reply.status_code == 400
    assert "nope-secret-name" not in reply.text


def test_watching_another_principals_session_is_not_found(client, tmp_path):
    reply = client.post(f"/behavior/watch/start?session_id=theirs&directory={tmp_path}")
    assert reply.status_code == 404


def test_watching_inside_the_workspace_starts(client, tmp_path, monkeypatch):
    started = []
    tracker = SimpleNamespace(start=lambda: started.append(1))
    monkeypatch.setattr(br, "get_tracker", lambda sid: None)
    monkeypatch.setattr(br, "create_tracker", lambda sid, path, *a: tracker)
    reply = client.post(f"/behavior/watch/start?session_id=mine&directory={tmp_path}")
    assert reply.json()["status"] == "started" and started == [1]


def test_the_session_socket_refuses_another_principals_session(client):
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/behavior/ws/session/theirs"):
            pass
    assert refused.value.code == 4003


@pytest.mark.asyncio
async def test_the_global_stream_sends_each_principal_only_its_sessions(monkeypatch):
    sent: list[str] = []

    class _Ws:
        app = SimpleNamespace(state=SimpleNamespace(container=_Container()))

        async def send_json(self, message):
            sent.append(message["session_id"])

    ws = _Ws()
    monkeypatch.setenv("WEEBOT_ENFORCE_SESSION_OWNERSHIP", "true")
    monkeypatch.setattr(br, "_ws_connections", [ws])
    monkeypatch.setattr(br, "_ws_principals", {ws: "anonymous"})
    for sid in ("mine", "theirs"):
        await br.broadcast_event(
            SimpleNamespace(event_type="created", timestamp="t", path="/p", session_id=sid,
                            agent_version="v")
        )
    assert sent == ["mine"]
