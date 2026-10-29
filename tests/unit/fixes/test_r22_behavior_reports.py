"""R22 (audit 2026-10-29): behavior reports answer on empty days and take only real dates.

On a day with no activity the reporter returned a dict without the three counts the
response model requires, and for an unknown session one without ``actions_by_type`` and
``start_time``: both were 500s. The date path parameter reached ``LEDGER_DIR / f"{date}.md"``
as a raw string, so ``..%5C..%5Cx`` left the ledger directory on Windows.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from weebot.core import behavior_reporting

# The routers package re-exports the APIRouter under the module's name; take the module.
behavior_router = importlib.import_module("weebot.interfaces.web.routers.behavior_router")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(behavior_reporting, "LEDGER_DIR", tmp_path / "ledger")
    app = FastAPI()
    app.include_router(behavior_router.router)
    return TestClient(app)


def test_an_empty_day_reports_zeros(client):
    for url in ("/behavior/report/today", "/behavior/report/2026-10-29"):
        response = client.get(url)
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["total_actions"], body["autonomous_count"], body["override_count"]) == (0, 0, 0)


def test_an_unknown_session_reports_zeros(client):
    response = client.get("/behavior/session/nobody")
    assert response.status_code == 200, response.text
    assert response.json()["actions_by_type"] == {} and response.json()["start_time"] is None


@pytest.mark.parametrize("date", ["..%5C..%5Cx", "2026-13-40", "yesterday"])
def test_only_a_real_date_is_accepted(client, date):
    assert client.get(f"/behavior/report/{date}").status_code == 422


def test_the_reporter_refuses_a_non_date_itself():
    with pytest.raises(ValueError):
        behavior_reporting.BehaviorReporter().get_date_report("../../secrets")
