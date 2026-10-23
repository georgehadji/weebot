"""Session search and dashboard counts show only the caller's sessions (F58).

`GET /api/sessions/search` returned matches from every user's sessions, and
`/api/dashboard/metrics` counted all sessions, unlike `GET /api/sessions`,
which filters by the caller.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from weebot.domain.models.session import Session


def _repo():
    sessions = {"a1": Session(id="a1", user_id="alice"), "b1": Session(id="b1", user_id="bob")}
    repo = MagicMock()
    repo.load_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    repo.list_sessions = AsyncMock(
        side_effect=lambda user_id=None, **kw: [s for s in sessions.values()
                                                if user_id in (None, s.user_id)]
    )
    return repo


async def test_search_returns_only_the_callers_sessions(monkeypatch):
    from weebot.interfaces.web.routers import sessions as router

    monkeypatch.setenv("WEEBOT_ENFORCE_SESSION_OWNERSHIP", "true")
    hits = [SimpleNamespace(session_id="a1"), SimpleNamespace(session_id="b1")]
    svc = MagicMock()
    svc.return_value.search = AsyncMock(return_value=hits)
    with patch("weebot.application.services.session_search_service.SessionSearchService", svc), \
         patch("weebot.interfaces.web.auth._resolve_user", AsyncMock(return_value="alice")):
        out = await router.search_sessions(q="x", limit=10, http_request=MagicMock(),
                                           state_repo=_repo())
    assert [r["session_id"] for r in out["results"]] == ["a1"]


async def test_dashboard_counts_only_the_callers_sessions(monkeypatch):
    from weebot.interfaces.web.routers import dashboard

    with patch.object(dashboard, "get_current_user_id", return_value="alice", create=True):
        out = await dashboard.get_dashboard_metrics(http_request=MagicMock(), state_repo=_repo())
    assert out.total_sessions == 1
