"""WEEBOT_BROWSER_CDP_URL: connect to a running CDP browser (Lightpanda) instead of launching.

Every Chromium launch site goes through ``open_chromium``. With the setting unset nothing
changes. With it set, the browser is ``connect_over_cdp(url)``; a proxy needs a launched
browser, so a proxied config still launches; an unreachable CDP endpoint falls back to a
launch with a warning, so browser tools keep working when the container is down.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from weebot.infrastructure.browser import playwright_adapter as pa


def _chromium(connect_error: Exception | None = None):
    return SimpleNamespace(
        launch=AsyncMock(return_value="launched"),
        connect_over_cdp=AsyncMock(
            side_effect=connect_error, return_value=None if connect_error else "connected"
        ),
    )


@pytest.fixture
def cdp_url(monkeypatch):
    from weebot.config.settings import get_settings

    def _set(value):
        monkeypatch.setattr(get_settings(), "browser_cdp_url", value, raising=False)

    return _set


@pytest.mark.asyncio
async def test_unset_launches_as_before(cdp_url):
    cdp_url(None)
    chromium = _chromium()
    assert await pa.open_chromium(chromium, {"headless": True}) == "launched"
    chromium.connect_over_cdp.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_connects_over_cdp(cdp_url):
    cdp_url("http://127.0.0.1:9222")
    chromium = _chromium()
    assert await pa.open_chromium(chromium, {"headless": True}) == "connected"
    chromium.connect_over_cdp.assert_awaited_once_with("http://127.0.0.1:9222")
    chromium.launch.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_proxied_config_still_launches(cdp_url):
    cdp_url("http://127.0.0.1:9222")
    chromium = _chromium()
    assert await pa.open_chromium(chromium, {"headless": True, "proxy": {"server": "x"}}) == (
        "launched"
    )
    chromium.connect_over_cdp.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unreachable_endpoint_falls_back_with_a_warning(cdp_url, caplog):
    cdp_url("http://127.0.0.1:9222")
    chromium = _chromium(connect_error=ConnectionRefusedError("refused"))
    with caplog.at_level(logging.WARNING):
        assert await pa.open_chromium(chromium, {"headless": True}) == "launched"
    assert any("CDP" in r.getMessage() for r in caplog.records)


def test_every_chromium_launch_site_uses_it():
    """Both long-lived launch sites, and the one-shot fetch in advanced_browser."""
    import inspect

    from weebot.infrastructure.browser import session_pool
    from weebot.tools import advanced_browser

    assert "open_chromium(" in inspect.getsource(pa.PlaywrightAdapter._launch)
    assert "open_chromium(" in inspect.getsource(session_pool)
    src = inspect.getsource(advanced_browser)
    assert "open_chromium(" in src and "chromium.launch(" not in src
