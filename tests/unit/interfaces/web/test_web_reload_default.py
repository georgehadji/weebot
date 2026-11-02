"""The web API must not auto-reload while agent sessions are running.

A session edits the repository the server runs from. Uvicorn's reloader restarts the
server on every ``.py`` change, which interrupts the session ("the server stopped while
this session was running") and leaves a worker that no longer answers requests.
"""

from weebot.interfaces.web.main import web_reload_enabled


def test_reload_is_off_by_default(monkeypatch):
    monkeypatch.delenv("WEEBOT_WEB_RELOAD", raising=False)
    assert web_reload_enabled() is False


def test_reload_can_be_opted_in(monkeypatch):
    monkeypatch.setenv("WEEBOT_WEB_RELOAD", "1")
    assert web_reload_enabled() is True
    monkeypatch.setenv("WEEBOT_WEB_RELOAD", "true")
    assert web_reload_enabled() is True


def test_reload_rejects_unexpected_values(monkeypatch):
    monkeypatch.setenv("WEEBOT_WEB_RELOAD", "nope")
    assert web_reload_enabled() is False
