"""H12b: the OpenAI-compatible API runs Weebot sessions and speaks chat-completion JSON."""

from __future__ import annotations

import asyncio
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai import OpenAI

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.idempotency_port import IdempotencyPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.event import (
    DoneEvent,
    ErrorEvent,
    MessageEvent,
    ToolApprovalEvent,
    ToolEvent,
    WaitForUserEvent,
)
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.idempotency_store import SQLiteIdempotencyStore
from weebot.interfaces.web import openai_adapter as adapter
from weebot.interfaces.web.routers import openai_compat, sessions as sessions_routes

KEY = "test-key-1"


class _Repo:
    def __init__(self):
        self.sessions: dict[str, Session] = {}

    async def load_session(self, session_id):
        return self.sessions.get(session_id)

    async def create_session(self, session):
        if session.id in self.sessions:
            return False
        self.sessions[session.id] = session
        return True

    async def save_session(self, session):
        self.sessions[session.id] = session


class _Bus:
    def __init__(self):
        self.handlers = []

    def subscribe(self, handler):
        self.handlers.append(handler)

    def unsubscribe(self, handler):
        self.handlers.remove(handler)

    async def publish(self, event):
        for handler in list(self.handlers):
            await handler(event)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("WEEBOT_API_KEY", KEY)
    repo, bus = _Repo(), _Bus()
    store = SQLiteIdempotencyStore(str(tmp_path / "idem.db"))
    ports = {StateRepositoryPort: repo, EventBusPort: bus, IdempotencyPort: store}
    app = FastAPI()
    app.state.container = types.SimpleNamespace(get=lambda key: ports[key])
    app.include_router(openai_compat.router)
    calls: list[tuple[str, str, dict]] = []
    script: list = []

    async def fake_dispatch(request, session, text, state_repo, **kwargs):
        calls.append((session.id, text, kwargs))
        running = session.model_copy(update={"status": SessionStatus.RUNNING})
        await state_repo.save_session(running)
        events = script or [
            MessageEvent(message=f"echo: {text}"),
            DoneEvent(status="completed"),
        ]
        for event in events:
            await bus.publish(event.model_copy(update={"session_id": session.id}))
        return types.SimpleNamespace(session=running, verb="start")

    monkeypatch.setattr(sessions_routes, "_dispatch_input", fake_dispatch)
    monkeypatch.setattr(openai_compat, "_persona_ids", lambda: ["reviewer"])
    http = TestClient(app, headers={"Authorization": f"Bearer {KEY}"})
    return types.SimpleNamespace(
        http=http, repo=repo, bus=bus, calls=calls, script=script, tmp_path=tmp_path
    )


def _client(env) -> OpenAI:
    return OpenAI(base_url="http://testserver/v1", api_key=KEY, http_client=env.http)


# ── adapter ────────────────────────────────────────────────────────────────────────────────


def test_a_message_becomes_a_content_delta_and_done_finishes_the_stream():
    kw = {"completion_id": "c1", "model": "weebot-auto", "created": 1}

    msg = adapter.to_openai_chunk(MessageEvent(message="hi"), **kw)
    end = adapter.to_openai_chunk(DoneEvent(), **kw)

    assert msg["choices"][0]["delta"] == {"content": "hi\n"}
    assert msg["choices"][0]["finish_reason"] is None
    assert end["choices"][0]["finish_reason"] == "stop"
    assert msg["object"] == "chat.completion.chunk"


def test_tool_steps_appear_only_when_asked_and_user_messages_never():
    kw = {"completion_id": "c1", "model": "m", "created": 1}
    call = ToolEvent(tool_name="bash", function_name="bash")

    assert adapter.to_openai_chunk(call, **kw) is None
    shown = adapter.to_openai_chunk(call, show_steps=True, **kw)
    assert "bash" in shown["choices"][0]["delta"]["content"]
    assert adapter.to_openai_chunk(MessageEvent(role="user", message="x"), **kw) is None


def test_a_run_that_waits_for_a_person_ends_the_reply_with_the_question():
    chunk = adapter.to_openai_chunk(
        WaitForUserEvent(question="Which file?"),
        completion_id="c",
        model="m",
        created=1,
    )

    assert "Which file?" in chunk["choices"][0]["delta"]["content"]
    assert chunk["choices"][0]["finish_reason"] == "stop"
    assert adapter.is_terminal(ToolApprovalEvent()) and not adapter.is_terminal(ErrorEvent())


def test_models_are_the_run_modes_and_personas():
    ids = [m["id"] for m in adapter.model_list(["reviewer"], 1)["data"]]

    assert ids == ["weebot-chat", "weebot-plan", "weebot-auto", "weebot-persona-reviewer"]
    assert adapter.resolve_model("weebot-auto", []) == ("auto", None)
    assert adapter.resolve_model("weebot-persona-reviewer", ["reviewer"]) == (
        "interactive",
        "reviewer",
    )
    assert adapter.resolve_model("gpt-4o", ["reviewer"]) is None


# ── chat completions through the official client ───────────────────────────────────────────


def test_the_openai_client_gets_a_reply(env):
    out = _client(env).chat.completions.create(
        model="weebot-auto", messages=[{"role": "user", "content": "hello"}]
    )

    assert out.choices[0].message.content == "echo: hello"
    assert out.choices[0].finish_reason == "stop"
    assert env.calls[0][1] == "hello" and env.calls[0][2]["execution_mode"] == "auto"


def test_the_openai_client_streams_a_reply(env):
    stream = _client(env).chat.completions.create(
        model="weebot-plan", messages=[{"role": "user", "content": "hello"}], stream=True
    )
    chunks = list(stream)

    text = "".join(c.choices[0].delta.content or "" for c in chunks)
    assert text == "echo: hello\n"
    assert chunks[-1].choices[0].finish_reason == "stop"
    assert env.bus.handlers == []  # the tap is closed


def test_the_last_user_message_is_the_prompt_and_text_parts_are_joined(env):
    _client(env).chat.completions.create(
        model="weebot-auto",
        messages=[
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": [{"type": "text", "text": "second"}]},
        ],
    )

    assert env.calls[0][1] == "second"


def test_client_supplied_tools_are_refused(env):
    r = env.http.post(
        "/v1/chat/completions",
        json={
            "model": "weebot-auto",
            "messages": [{"role": "user", "content": "x"}],
            "tools": [{"type": "function", "function": {"name": "f"}}],
        },
    )

    assert r.status_code == 400 and env.calls == []


def test_an_unknown_model_is_404(env):
    r = env.http.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "x"}]},
    )

    assert r.status_code == 404 and env.calls == []


def test_the_session_header_resumes_the_same_session(env):
    body = {"model": "weebot-auto", "messages": [{"role": "user", "content": "one"}]}
    first = env.http.post("/v1/chat/completions", json=body)
    sid = first.headers["X-Weebot-Session"]
    second = env.http.post(
        "/v1/chat/completions",
        json={**body, "messages": [{"role": "user", "content": "two"}]},
        headers={"X-Weebot-Session": sid},
    )

    assert second.headers["X-Weebot-Session"] == sid
    assert [c[0] for c in env.calls] == [sid, sid]
    assert len(env.repo.sessions) == 1


def test_another_principals_session_is_404_and_nothing_runs(env):
    env.repo.sessions["theirs"] = Session(id="theirs", user_id="someone-else")

    r = env.http.post(
        "/v1/chat/completions",
        json={"model": "weebot-auto", "messages": [{"role": "user", "content": "x"}]},
        headers={"X-Weebot-Session": "theirs"},
    )

    assert r.status_code == 404 and env.calls == []


def test_a_run_that_pauses_for_approval_ends_the_reply_and_names_the_ask(env):
    env.script[:] = [ToolApprovalEvent(tool_name="bash", prompt="Allow this command?")]

    out = _client(env).chat.completions.create(
        model="weebot-plan", messages=[{"role": "user", "content": "rm x"}]
    )

    assert "approval needed" in out.choices[0].message.content


# ── runs ───────────────────────────────────────────────────────────────────────────────────


def test_a_repeated_idempotency_key_returns_the_same_run_and_starts_one(env):
    headers = {"Idempotency-Key": "k-1"}
    body = {"input": "do it", "model": "weebot-auto"}

    first = env.http.post("/v1/runs", json=body, headers=headers).json()
    again = env.http.post("/v1/runs", json=body, headers=headers).json()

    assert first["id"] == again["id"] and first["object"] == "run"
    assert len(env.calls) == 1


def test_a_failed_start_frees_the_key_for_a_retry(env, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("no flow")

    real = sessions_routes._dispatch_input
    monkeypatch.setattr(sessions_routes, "_dispatch_input", boom)
    headers = {"Idempotency-Key": "k-2"}
    body = {"input": "do it", "model": "weebot-auto"}
    with pytest.raises(RuntimeError):
        env.http.post("/v1/runs", json=body, headers=headers)

    monkeypatch.setattr(sessions_routes, "_dispatch_input", real)

    assert env.http.post("/v1/runs", json=body, headers=headers).status_code == 200


def test_the_events_of_a_finished_run_are_one_done_event(env):
    run = env.http.post("/v1/runs", json={"input": "x", "model": "weebot-auto"}).json()
    env.repo.sessions[run["id"]] = env.repo.sessions[run["id"]].model_copy(
        update={"status": SessionStatus.COMPLETED}
    )

    r = env.http.get(f"/v1/runs/{run['id']}/events")

    assert "event: done" in r.text and "completed" in r.text


def test_another_principals_run_is_404_everywhere(env):
    env.repo.sessions["theirs"] = Session(id="theirs", user_id="someone-else")

    for method, path in [
        ("get", "/v1/runs/theirs/events"),
        ("post", "/v1/runs/theirs/stop"),
    ]:
        assert getattr(env.http, method)(path).status_code == 404
    approval = {"call_id": "c1", "decision": "approve"}
    assert env.http.post("/v1/runs/theirs/approval", json=approval).status_code == 404


def test_approval_needs_a_waiting_run_and_maps_the_scope_to_the_reply(env):
    run = env.http.post("/v1/runs", json={"input": "x", "model": "weebot-auto"}).json()
    approval = {"call_id": "c1", "decision": "approve", "scope": "session"}
    assert env.http.post(f"/v1/runs/{run['id']}/approval", json=approval).status_code == 409

    def wait():
        env.repo.sessions[run["id"]] = env.repo.sessions[run["id"]].model_copy(
            update={"status": SessionStatus.WAITING}
        )

    wait()
    env.calls.clear()
    ok = env.http.post(f"/v1/runs/{run['id']}/approval", json=approval)
    wait()
    deny = env.http.post(
        f"/v1/runs/{run['id']}/approval", json={"call_id": "c1", "decision": "deny"}
    )

    assert ok.status_code == 200 and deny.status_code == 200
    assert [c[1] for c in env.calls] == ["session", "no"]


def test_the_tap_ends_at_the_first_terminal_event_and_unsubscribes():
    async def go():
        bus = _Bus()
        tap = openai_compat._Tap(bus, "s1")
        await bus.publish(MessageEvent(session_id="other", message="not mine"))
        await bus.publish(MessageEvent(session_id="s1", message="mine"))
        await bus.publish(DoneEvent(session_id="s1"))
        await bus.publish(MessageEvent(session_id="s1", message="after"))
        return [e async for e in tap.events()], bus.handlers

    events, handlers = asyncio.run(go())

    assert [getattr(e, "message", "done") for e in events] == ["mine", "done"]
    assert handlers == []


# ── mounting ───────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("flag,expected", [("0", False), ("1", True)])
def test_the_router_is_mounted_only_when_the_flag_is_set(monkeypatch, flag, expected):
    from weebot.config.settings import get_settings
    from weebot.interfaces.web.main import create_app

    monkeypatch.setenv("WEEBOT_OPENAI_API_ENABLED", flag)
    get_settings.cache_clear()
    try:
        paths = set(create_app().openapi()["paths"])
    finally:
        get_settings.cache_clear()

    assert ("/v1/chat/completions" in paths) is expected
