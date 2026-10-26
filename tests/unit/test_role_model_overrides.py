"""The UI's per-role model pick goes first in the cascade and keeps the defaults as fallback."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from weebot.config import role_overrides
from weebot.config.model_refs import ROLE_MODEL_CONFIG, get_model_cascade_for_role
from weebot.interfaces.web.auth import require_mutation_identity
from weebot.interfaces.web.routers.models import router


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(role_overrides, "overrides_path", lambda: tmp_path / "role_models.json")
    monkeypatch.setattr(role_overrides, "_cache", None)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[require_mutation_identity] = lambda: "tester"
    return TestClient(app)


def test_override_goes_first_and_defaults_stay_as_fallback(client):
    default = list(ROLE_MODEL_CONFIG["executor"])
    pick = default[-1]
    assert client.put("/api/models/roles/executor", json={"model": pick}).status_code == 200
    cascade = get_model_cascade_for_role("executor")
    assert cascade[0] == pick
    assert sorted(cascade) == sorted(default)  # nothing lost, nothing duplicated


def test_reset_restores_the_default(client):
    before = get_model_cascade_for_role("planner")
    client.put("/api/models/roles/planner", json={"model": ROLE_MODEL_CONFIG["coder"][0]})
    row = client.delete("/api/models/roles/planner").json()
    assert row["override"] is None
    assert get_model_cascade_for_role("planner") == before


def test_listing_reports_every_role(client):
    rows = client.get("/api/models/roles").json()
    assert {r["role"] for r in rows} == set(ROLE_MODEL_CONFIG)
    assert all(r["effective"] == r["default"][0] for r in rows)


def test_unknown_role_and_model_are_rejected(client):
    assert client.put("/api/models/roles/nope", json={"model": "x"}).status_code == 404
    assert client.put("/api/models/roles/executor", json={"model": "nope/none"}).status_code == 400
    assert client.delete("/api/models/roles/nope").status_code == 404
