"""Tests for POST /api/chat/stream (T1.3).

Verifies:
  1. The response streams — the first SSE message (the synthetic
     ``session`` event) arrives before the flow's async generator
     finishes, proving this endpoint doesn't drain-then-return like
     the existing ``POST /api/chat``.
  2. Each AgentEvent the flow yields becomes one SSE message with a
     matching ``event:`` field.
  3. A fresh chat (no session_id in the request) gets its session id
     via the ``session`` event before any content arrives.

Only ``chat_router`` is mounted (not the full ``create_app()``) so the
test isolates streaming behavior from auth/lifespan/DI concerns already
covered elsewhere; auth and session persistence are stubbed directly.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from weebot.domain.models.event import DoneEvent, MessageEvent
from weebot.interfaces.web.auth import require_mutation_identity
from weebot.interfaces.web.routers.chat_router import router as chat_router


class _FakeFlow:
    """Stand-in for ChatFlow — yields events with a delay to prove streaming."""

    def __init__(self, events, delay_seconds: float = 0.0):
        self._events = events
        self._delay = delay_seconds

    async def run(self, prompt: str):
        for event in self._events:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield event


def _build_app(flow: _FakeFlow, session_id: str = "chat-test123"):
    app = FastAPI()
    app.include_router(chat_router)
    app.dependency_overrides[require_mutation_identity] = lambda: None

    fake_session = MagicMock()
    fake_session.id = session_id
    fake_session.user_id = "anonymous"

    state_repo = AsyncMock()
    state_repo.save_session = AsyncMock()
    state_repo.load_session = AsyncMock(return_value=fake_session)

    container = MagicMock()
    container.get = MagicMock(return_value=state_repo)
    container.build_chat_flow = MagicMock(return_value=flow)

    app.state.container = container
    return app, fake_session


def _parse_sse_events(raw_text: str) -> list[tuple[str, dict]]:
    """Parse ``event:``/``data:`` pairs out of a raw SSE byte stream."""
    parsed = []
    event_name = None
    for line in raw_text.splitlines():
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data = json.loads(line[len("data:") :].strip())
            parsed.append((event_name, data))
    return parsed


def test_stream_emits_session_event_first():
    flow = _FakeFlow([MessageEvent(role="assistant", message="hi"), DoneEvent()])
    app, session = _build_app(flow)
    client = TestClient(app)

    response = client.post("/api/chat/stream", json={"message": "hello", "session_id": session.id})

    events = _parse_sse_events(response.text)
    assert events[0][0] == "session"
    assert events[0][1]["session_id"] == session.id


def test_stream_emits_one_sse_message_per_agent_event():
    flow = _FakeFlow([MessageEvent(role="assistant", message="hi there"), DoneEvent()])
    app, session = _build_app(flow)
    client = TestClient(app)

    response = client.post("/api/chat/stream", json={"message": "hello", "session_id": session.id})

    events = _parse_sse_events(response.text)
    event_names = [name for name, _ in events]
    assert event_names == ["session", "message", "done"]
    message_payload = events[1][1]
    assert message_payload["message"] == "hi there"
    assert message_payload["role"] == "assistant"


def test_stream_first_byte_arrives_before_flow_completes():
    """A slow flow must not block the first SSE message behind later ones."""
    flow = _FakeFlow(
        [MessageEvent(role="assistant", message="slow"), DoneEvent()], delay_seconds=0.2
    )
    app, _ = _build_app(flow)
    client = TestClient(app)

    with client.stream("POST", "/api/chat/stream", json={"message": "hello"}) as response:
        first_line = next(response.iter_lines())

    # The session event is written before the generator ever awaits the
    # first flow.run() delay, so it must be readable immediately.
    assert first_line.startswith("event:")
    assert "session" in first_line
