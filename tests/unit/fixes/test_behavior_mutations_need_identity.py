"""Behavior and ponytail mutations need an identity, like every other mutation (F59).

The five behavior POSTs (override, watch start/stop, self-knowledge
regenerate) and `POST /ponytail/mode/{mode}` had no `require_mutation_identity`;
`watch/start` starts a file watcher on any directory the caller names. The
global key middleware covers most deployments; this is the per-route check the
rest of the API already has.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(router):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)  # host "testclient": anonymous and not loopback


@pytest.mark.parametrize(
    "path",
    [
        "/behavior/override",
        "/behavior/watch/start?session_id=s&directory=C:/",
        "/behavior/watch/stop?session_id=s",
        "/behavior/self-knowledge/regenerate",
    ],
)
def test_behavior_posts_refuse_anonymous_remote_callers(path, monkeypatch):
    monkeypatch.delenv("WEEBOT_API_KEY", raising=False)
    from weebot.interfaces.web.routers.behavior_router import router

    assert _client(router).post(path, json={}).status_code == 403


def test_ponytail_mode_refuses_anonymous_remote_callers(monkeypatch):
    monkeypatch.delenv("WEEBOT_API_KEY", raising=False)
    from weebot.interfaces.web.routers.ponytail import router

    assert _client(router).post("/ponytail/mode/lite").status_code == 403
