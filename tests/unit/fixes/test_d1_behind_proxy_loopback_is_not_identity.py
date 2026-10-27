"""D1: behind the UI proxy every request arrives from loopback, so loopback proves nothing.

With WEEBOT_BEHIND_PROXY=1 a mutation without a verified key is refused even from 127.0.0.1.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Depends
from starlette.testclient import TestClient

from weebot.interfaces.web.auth import require_mutation_identity

KEY = "sekret-key-for-test"


def _client(host: str) -> TestClient:
    app = FastAPI()

    @app.post("/m")
    async def mutate(_=Depends(require_mutation_identity)):
        return {"ok": True}

    return TestClient(app, client=(host, 5000))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("WEEBOT_API_KEY", raising=False)
    monkeypatch.delenv("WEEBOT_BEHIND_PROXY", raising=False)
    monkeypatch.delenv("WEEBOT_AUTH_MODE", raising=False)


def test_by_default_loopback_may_mutate_without_a_key():
    assert _client("127.0.0.1").post("/m").status_code == 200


def test_behind_the_proxy_loopback_without_a_key_is_refused(monkeypatch):
    monkeypatch.setenv("WEEBOT_BEHIND_PROXY", "1")
    assert _client("127.0.0.1").post("/m").status_code == 403


def test_behind_the_proxy_a_valid_key_still_works(monkeypatch):
    monkeypatch.setenv("WEEBOT_BEHIND_PROXY", "1")
    monkeypatch.setenv("WEEBOT_API_KEY", KEY)
    assert _client("127.0.0.1").post("/m", headers={"X-API-Key": KEY}).status_code == 200


def test_behind_the_proxy_a_wrong_key_is_refused(monkeypatch):
    monkeypatch.setenv("WEEBOT_BEHIND_PROXY", "1")
    monkeypatch.setenv("WEEBOT_API_KEY", KEY)
    assert _client("127.0.0.1").post("/m", headers={"X-API-Key": "no"}).status_code == 403


@pytest.mark.parametrize("value", ["0", "false", "off", ""])
def test_other_values_leave_loopback_trust_alone(monkeypatch, value):
    monkeypatch.setenv("WEEBOT_BEHIND_PROXY", value)
    assert _client("127.0.0.1").post("/m").status_code == 200
