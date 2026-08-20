"""Unit tests for the Ponytail web router."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from weebot.interfaces.web.routers.ponytail import router


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Build a TestClient for the Ponytail router in isolation."""
    # Redirect the project-local mode file into a temp directory so tests do
    # not mutate the real workspace state.
    monkeypatch.setattr(
        "cli.commands.ponytail._PONYTAIL_MODE_FILE", tmp_path / "ponytail_mode.json"
    )

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_get_mode_defaults_to_off(client):
    response = client.get("/api/ponytail/mode")
    assert response.status_code == 200
    assert response.json() == {"mode": "off"}


def test_set_mode_to_valid_value(client):
    response = client.post("/api/ponytail/mode/full")
    assert response.status_code == 200
    assert response.json() == {"mode": "full"}

    response = client.get("/api/ponytail/mode")
    assert response.json() == {"mode": "full"}


def test_set_mode_to_invalid_value(client):
    response = client.post("/api/ponytail/mode/nope")
    assert response.status_code == 400
    assert "off" in response.json()["detail"]
