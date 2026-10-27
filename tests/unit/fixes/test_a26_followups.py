"""A26 follow-ups: what the five A26 parts left behind.

- xAI and Ideogram direct media paths were not metered, and a paid 200 with nothing usable
  fell through to OpenRouter (or the next model) and bought the image again.
- The video tool's stop after a paid empty answer had no test.
- Planner calls ran without a deadline, so the retry layer below could sleep its whole ladder.
- A hedge probe cancelled while still queued for an LLM pool slot was billed, though it never
  sent a request.
- Callers of ``list_sessions()`` that need every session saw only the newest 100.
"""

from __future__ import annotations

import asyncio
import unittest.mock as m
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.ports.llm_port import LLMResponse
from weebot.domain.models.session import SessionStatus

# ── fake aiohttp ────────────────────────────────────────────────────────────


class _Resp:
    def __init__(self, body: dict, status: int = 200) -> None:
        self.status = status
        self._body = body

    async def json(self):
        return self._body

    async def text(self):
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session:
    """Every POST answers 200 with *body*; every GET (a download) fails."""

    def __init__(self, posts: list, body: dict) -> None:
        self._posts = posts
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def post(self, url, *a, **k):
        self._posts.append(url)
        return _Resp(self._body)

    def get(self, url, *a, **k):
        return _Resp({}, status=500)


@pytest.fixture
def media_spend(monkeypatch):
    from weebot.core import media_spend as ms

    seen: list = []

    async def sink(event):
        seen.append(event.model)

    ms.set_media_spend_sink(sink)
    yield seen
    ms.set_media_spend_sink(None)


def _fake_http(monkeypatch, body: dict) -> list:
    import aiohttp

    posts: list = []
    monkeypatch.setattr(aiohttp, "ClientSession", lambda *a, **k: _Session(posts, body))
    return posts


# Test values, never sent anywhere: every request goes to the fake session above.
_KEYS = {
    "OPENROUTER_API_KEY": "test-key-openrouter",
    "XAI_API_KEY": "test-key-xai",
    "IDEOGRAM_API_KEY": "test-key-ideogram",
}


# ── 1. direct media paths ───────────────────────────────────────────────────


async def test_xai_direct_image_with_nothing_usable_is_metered_and_not_bought_again(
    monkeypatch, tmp_path, media_spend
):
    from weebot.tools.image_gen_tool import ImageGenParams, ImageGenTool

    for k, v in _KEYS.items():
        monkeypatch.setenv(k, v)
    posts = _fake_http(monkeypatch, {"data": []})
    params = ImageGenParams(
        prompt="a cat",
        model="x-ai/grok-imagine-image-quality",
        output_path=str(tmp_path / "cat.png"),
    )
    await ImageGenTool()._execute_openrouter(params)
    assert len(posts) == 1, posts  # no second purchase through OpenRouter
    assert media_spend == ["x-ai/grok-imagine-image-quality"]


async def test_xai_direct_image_whose_download_fails_is_not_bought_again(
    monkeypatch, tmp_path, media_spend
):
    from weebot.tools.image_gen_tool import ImageGenParams, ImageGenTool

    for k, v in _KEYS.items():
        monkeypatch.setenv(k, v)
    posts = _fake_http(monkeypatch, {"data": [{"url": "https://img.example/cat.png"}]})
    params = ImageGenParams(
        prompt="a cat",
        model="x-ai/grok-imagine-image-quality",
        output_path=str(tmp_path / "cat.png"),
    )
    await ImageGenTool()._execute_openrouter(params)
    assert len(posts) == 1, posts
    assert media_spend == ["x-ai/grok-imagine-image-quality"]


async def test_ideogram_direct_with_nothing_usable_stops_the_cascade(
    monkeypatch, tmp_path, media_spend
):
    import weebot.config.model_refs as refs
    from weebot.tools.image_gen_tool import ImageGenParams, ImageGenTool

    for k, v in _KEYS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setitem(
        refs.IMAGE_CASCADE, "general", ["ideogram/ideogram-v3-turbo", "other/image-model"]
    )
    posts = _fake_http(monkeypatch, {"data": []})
    params = ImageGenParams(prompt="a logo", output_path=str(tmp_path / "logo.png"))
    await ImageGenTool()._execute_openrouter(params)
    assert len(posts) == 1, posts  # the next model is not bought
    assert media_spend == ["ideogram/ideogram-v3-turbo"]


async def test_xai_direct_video_with_no_url_is_metered_and_not_bought_again(
    monkeypatch, tmp_path, media_spend
):
    from weebot.tools.video_gen_tool import VideoGenParams, VideoGenTool

    for k, v in _KEYS.items():
        monkeypatch.setenv(k, v)
    posts = _fake_http(monkeypatch, {"choices": [{"message": {"content": "no video"}}]})
    params = VideoGenParams(
        prompt="a cat", model="x-ai/grok-imagine-video", output_path=str(tmp_path / "cat.mp4")
    )
    await VideoGenTool()._execute_openrouter(params)
    assert len(posts) == 1, posts
    assert media_spend == ["x-ai/grok-imagine-video"]


# ── 3. video over OpenRouter ────────────────────────────────────────────────


async def test_a_paid_openrouter_video_with_no_url_stops_the_cascade(
    monkeypatch, tmp_path, media_spend
):
    import weebot.config.model_refs as refs
    from weebot.tools.video_gen_tool import VideoGenParams, VideoGenTool

    monkeypatch.setenv("OPENROUTER_API_KEY", _KEYS["OPENROUTER_API_KEY"])
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setitem(refs.VIDEO_CASCADE, "general", ["first/video", "second/video"])
    posts = _fake_http(monkeypatch, {"choices": [{"message": {"content": "no video"}}]})
    params = VideoGenParams(prompt="a cat", output_path=str(tmp_path / "cat.mp4"))
    result = await VideoGenTool()._execute_openrouter(params)
    assert len(posts) == 1, posts
    assert media_spend == ["first/video"]
    assert "billed" in (result.error or "")


# ── 2. planner deadline ─────────────────────────────────────────────────────


async def test_planner_calls_run_inside_a_deadline():
    from weebot.application.agents.planner import PlannerAgent
    from weebot.utils.backoff import call_deadline

    seen: list = []

    class _Llm:
        async def chat(self, **kwargs):
            seen.append(call_deadline.get())
            return LLMResponse(
                content='{"goal": "g", "title": "t", "steps": [{"id": "1", "description": "d"}]}',
                tool_calls=None,
                usage=None,
            )

    planner = PlannerAgent(llm=_Llm())
    async for _event in planner.create_plan("do a thing"):
        pass
    assert seen and all(d is not None for d in seen)


# ── 4. a probe still queued for a pool slot sent nothing ────────────────────


async def _ident(models, *a, **k):
    return models


async def test_a_probe_cancelled_while_queued_for_a_slot_is_not_billed(monkeypatch):
    import weebot.config.model_refs as refs
    from weebot.application.strategies.llm_pool import LLMPool

    monkeypatch.setattr(
        refs, "get_model_cascade_for_role", lambda role: ["first/ok", "last/queued"]
    )
    for tier in ("_TIER2_MODEL", "_TIER3_MODEL", "_TIER4_MODEL"):
        monkeypatch.setattr(CascadeExecutor, tier, "dead/never", raising=False)
    monkeypatch.setattr(CascadeExecutor, "get_credits_and_filter_direct", staticmethod(_ident))

    class _Llm:
        async def chat(self, **kwargs):
            await asyncio.sleep(0.2)
            return LLMResponse(content="ok", tool_calls=None, usage=None)

    billed: list = []

    async def on_done(event):
        billed.append((event.model, event.estimated))

    tools = m.MagicMock()
    tools.to_params.return_value = []
    ex = CascadeExecutor(
        llm=_Llm(),
        tools=tools,
        agent_role=None,
        model_provider=lambda d: ["next/queued"],
        on_success=None,
        llm_pool=LLMPool(max_concurrent=1),
        on_call_completed=on_done,
    )
    # Launch all three probes at once. The pool admits one; when it finishes, the slot goes
    # to "next/queued" (which then sends, and is rightly billed), and "last/queued" is
    # cancelled still waiting for a slot.
    ex._HEDGE_DELAY_S = 0.0
    await ex.call_with_cascade(messages=[{"role": "user", "content": "x"}], description="d")
    assert ("first/ok", False) in billed
    assert not any(model == "last/queued" for model, _ in billed), billed


# ── 6. callers that need every session ──────────────────────────────────────


class _PagedRepo:
    """Honours user_id, status, limit and offset like SQLite; default limit is 100."""

    def __init__(self, sessions: list) -> None:
        self.sessions = sessions

    async def list_sessions(self, user_id=None, status=None, limit=100, offset=0, **_kw):
        rows = [
            s
            for s in self.sessions
            if (status is None or s.status.value == status)
            and (user_id is None or s.user_id == user_id)
        ]
        return rows[offset : offset + limit]


def _sessions(completed: int, running: int) -> list:
    old = datetime.now(UTC) - timedelta(days=2)
    done = [
        SimpleNamespace(
            id=f"c{i}", session_id=f"c{i}", user_id="u", status=SessionStatus.COMPLETED,
            updated_at=datetime.now(UTC),
        )
        for i in range(completed)
    ]
    stuck = [
        SimpleNamespace(
            id=f"r{i}", session_id=f"r{i}", user_id="u", status=SessionStatus.RUNNING,
            updated_at=old,
        )
        for i in range(running)
    ]
    return done + stuck  # newest first, as the repository orders them


async def test_the_staleness_monitor_sees_stuck_sessions_past_the_first_hundred():
    from weebot.infrastructure.monitors.session_staleness_monitor import (
        SessionStalenessMonitor,
    )

    report = await SessionStalenessMonitor(_PagedRepo(_sessions(150, 5))).check()
    assert len(report.metadata.get("stale_ids", [])) == 5, report


def test_the_mcp_state_resource_counts_every_session():
    import json

    from weebot.mcp.resources import build_state_json

    state = json.loads(build_state_json(_PagedRepo(_sessions(150, 5))))
    assert state["total_sessions"] == 155
    assert state["active_sessions"] == 5


async def test_the_dashboard_counts_every_session(monkeypatch):
    from weebot.interfaces.web.routers import dashboard

    monkeypatch.setattr(dashboard, "get_current_user_id", lambda _req: "u")
    resp = await dashboard.get_dashboard_metrics(
        SimpleNamespace(), state_repo=_PagedRepo(_sessions(150, 5))
    )
    assert resp.total_sessions == 155
    assert resp.active_sessions == 5
    assert resp.completed_sessions == 150
