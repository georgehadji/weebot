"""browser_launcher: the one place that decides connect, launch or refuse.

WEEBOT_BROWSER_CDP_URL points the Chromium launch sites at a running CDP browser (Lightpanda).
The policy is fail closed: when that browser is down, or the request needs a local browser
(proxy, headless=False), the call is refused unless WEEBOT_BROWSER_CDP_FALLBACK is on. The
agent controls ``headless`` through a tool argument, so a launch-only option must never be a
quiet way out of the container.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from weebot.infrastructure.browser import browser_launcher as bl
from weebot.infrastructure.browser.browser_launcher import (
    CdpBrowserUnavailable,
    CdpSettings,
    plan_launch,
    redact_endpoint,
)

URL = "http://127.0.0.1:9222"
TOKEN_URL = "ws://user:s3cret@10.0.0.5:9222/devtools/browser/abc?token=tok-12345#frag"
HEADLESS = {"headless": True}


def _cdp(url=URL, fallback=False):
    return CdpSettings(url=url, fallback=fallback)


# --- pure core -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "options", "cdp", "breaker_open", "mode"),
    [
        ("chromium", HEADLESS, _cdp(None), False, "launch"),
        ("chromium", {"headless": False, "proxy": {"server": "x"}}, _cdp(None), True, "launch"),
        ("firefox", HEADLESS, _cdp(), False, "launch"),
        ("webkit", {"headless": False}, _cdp(), True, "launch"),
        ("chromium", HEADLESS, _cdp(), False, "connect"),
        ("chromium", {"headless": True, "proxy": {"server": "x"}}, _cdp(), False, "refuse"),
        ("chromium", {"headless": True, "proxy": {"server": "x"}}, _cdp(fallback=True), False,
         "launch"),
        ("chromium", {"headless": False}, _cdp(), False, "refuse"),
        ("chromium", {"headless": False}, _cdp(fallback=True), False, "launch"),
        ("chromium", HEADLESS, _cdp(), True, "refuse"),
        ("chromium", HEADLESS, _cdp(fallback=True), True, "launch"),
    ],
)
def test_plan_launch_table(name, options, cdp, breaker_open, mode):
    assert plan_launch(name, options, cdp, breaker_open).mode == mode


def test_refusal_names_the_launch_only_option():
    plan = plan_launch("chromium", {"headless": False, "proxy": {"server": "x"}}, _cdp(), False)
    assert plan.mode == "refuse"
    assert "headless=False" in plan.reason and "proxy" in plan.reason
    assert "WEEBOT_BROWSER_CDP_URL" in plan.reason


def test_refusal_for_a_down_endpoint_says_so():
    plan = plan_launch("chromium", HEADLESS, _cdp(), True)
    assert plan.mode == "refuse" and "unavailable" in plan.reason


def test_plan_launch_ignores_the_input_options_dict():
    options = {"headless": False}
    plan_launch("chromium", options, _cdp(fallback=True), False)
    assert options == {"headless": False}


# --- redaction -----------------------------------------------------------------------------


def test_redact_keeps_scheme_host_and_port_only():
    assert redact_endpoint(TOKEN_URL) == "ws://10.0.0.5:9222"
    assert redact_endpoint("http://localhost") == "http://localhost"
    assert redact_endpoint("http://[::1]:9222/x?t=1") == "http://[::1]:9222"


@pytest.mark.parametrize("bad", ["", "not a url", "http://host:notaport"])
def test_redact_survives_garbage(bad):
    assert redact_endpoint(bad) == "<invalid CDP url>"


# --- imperative shell ----------------------------------------------------------------------


def _browser_type(name="chromium", connect_error: Exception | None = None):
    return SimpleNamespace(
        name=name,
        launch=AsyncMock(return_value="launched"),
        connect_over_cdp=AsyncMock(
            side_effect=connect_error, return_value=None if connect_error else "connected"
        ),
    )


@pytest.fixture(autouse=True)
def _fresh_breaker(monkeypatch):
    monkeypatch.setattr(bl, "_breaker", bl._new_breaker())


@pytest.fixture
def cdp(monkeypatch):
    from weebot.config.settings import get_settings

    def _set(url=URL, *, fallback=False, timeout_ms=5000):
        settings = get_settings()
        monkeypatch.setattr(settings, "browser_cdp_url", url, raising=False)
        monkeypatch.setattr(settings, "browser_cdp_fallback", fallback, raising=False)
        monkeypatch.setattr(settings, "browser_cdp_connect_timeout_ms", timeout_ms, raising=False)

    return _set


@pytest.mark.asyncio
async def test_unset_launches_and_never_touches_cdp(cdp):
    cdp(None)
    bt = _browser_type()
    assert await bl.open_browser(bt, HEADLESS) == "launched"
    bt.connect_over_cdp.assert_not_awaited()
    bt.launch.assert_awaited_once_with(headless=True)


@pytest.mark.asyncio
async def test_connect_passes_the_timeout(cdp):
    cdp(timeout_ms=1234)
    bt = _browser_type()
    assert await bl.open_browser(bt, HEADLESS) == "connected"
    bt.connect_over_cdp.assert_awaited_once_with(URL, timeout=1234)
    bt.launch.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_down_endpoint_is_refused_by_default(cdp):
    cdp()
    bt = _browser_type(connect_error=ConnectionRefusedError("refused"))
    with pytest.raises(CdpBrowserUnavailable):
        await bl.open_browser(bt, HEADLESS)
    bt.launch.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_down_endpoint_launches_when_the_operator_opted_in(cdp):
    cdp(fallback=True)
    bt = _browser_type(connect_error=ConnectionRefusedError("refused"))
    assert await bl.open_browser(bt, HEADLESS) == "launched"


@pytest.mark.asyncio
async def test_one_failure_is_remembered_so_the_next_call_skips_the_wait(cdp):
    cdp()
    bt = _browser_type(connect_error=TimeoutError())
    with pytest.raises(CdpBrowserUnavailable):
        await bl.open_browser(bt, HEADLESS)
    with pytest.raises(CdpBrowserUnavailable):
        await bl.open_browser(bt, HEADLESS)
    assert bt.connect_over_cdp.await_count == 1


@pytest.mark.asyncio
async def test_after_the_cooldown_one_probe_goes_through(cdp):
    cdp()
    bt = _browser_type(connect_error=TimeoutError())
    with pytest.raises(CdpBrowserUnavailable):
        await bl.open_browser(bt, HEADLESS)
    bl._breaker._breakers[redact_endpoint(URL)].last_state_change -= 31
    bt.connect_over_cdp.side_effect = None
    bt.connect_over_cdp.return_value = "connected"
    assert await bl.open_browser(bt, HEADLESS) == "connected"
    assert bt.connect_over_cdp.await_count == 2
    # recovered: the breaker is closed again
    assert await bl.open_browser(bt, HEADLESS) == "connected"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options", [{"headless": False}, {"headless": True, "proxy": {"server": "x"}}]
)
async def test_launch_only_options_are_refused_without_a_connect_attempt(cdp, options):
    cdp()
    bt = _browser_type()
    with pytest.raises(CdpBrowserUnavailable, match="WEEBOT_BROWSER_CDP_URL"):
        await bl.open_browser(bt, options)
    bt.connect_over_cdp.assert_not_awaited()
    bt.launch.assert_not_awaited()


@pytest.mark.asyncio
async def test_launch_only_options_launch_locally_when_opted_in(cdp):
    cdp(fallback=True)
    bt = _browser_type()
    assert await bl.open_browser(bt, {"headless": False}) == "launched"
    bt.launch.assert_awaited_once_with(headless=False)
    bt.connect_over_cdp.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_engines_ignore_cdp(cdp):
    cdp()
    bt = _browser_type(name="firefox")
    assert await bl.open_browser(bt, {"headless": False}) == "launched"
    bt.connect_over_cdp.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_token_never_reaches_logs_or_errors(cdp, caplog):
    cdp(TOKEN_URL)
    bt = _browser_type(connect_error=OSError(f"cannot reach {TOKEN_URL}"))
    with caplog.at_level(logging.DEBUG), pytest.raises(CdpBrowserUnavailable) as err:
        await bl.open_browser(bt, HEADLESS)
    seen = caplog.text + str(err.value)
    for secret in ("s3cret", "tok-12345", "abc", "user:"):
        assert secret not in seen
    assert "10.0.0.5:9222" in seen
    # the raw url is only ever handed to Playwright
    assert bt.connect_over_cdp.await_args.args[0] == TOKEN_URL


@pytest.mark.asyncio
async def test_a_fallback_launch_warns_once_per_trip(cdp, caplog):
    cdp(fallback=True)
    bt = _browser_type(connect_error=ConnectionRefusedError("refused"))
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            assert await bl.open_browser(bt, HEADLESS) == "launched"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1


# --- launch sites: behaviour, not source text ----------------------------------------------


class _FakePlaywright:
    """Stands in for the Playwright driver: three engines, each a recording browser type."""

    def __init__(self, connect_error: Exception | None = None):
        self.chromium = _browser_type("chromium", connect_error)
        self.firefox = _browser_type("firefox")
        self.webkit = _browser_type("webkit")


def _live_browser():
    page = SimpleNamespace()
    context = SimpleNamespace(new_page=AsyncMock(return_value=page))
    return SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())


def _adapter(pw, **config):
    from weebot.application.ports.browser_port import BrowserConfig
    from weebot.infrastructure.browser.playwright_adapter import PlaywrightAdapter

    adapter = PlaywrightAdapter()
    adapter._playwright = pw
    adapter._config = BrowserConfig(**config)
    return adapter


@pytest.mark.asyncio
async def test_adapter_connects_chromium_over_cdp(cdp):
    cdp()
    pw = _FakePlaywright()
    pw.chromium.connect_over_cdp.return_value = _live_browser()
    adapter = _adapter(pw)
    await adapter._launch()
    pw.chromium.connect_over_cdp.assert_awaited_once()
    pw.chromium.launch.assert_not_awaited()
    assert adapter._page is not None


@pytest.mark.asyncio
async def test_adapter_refuses_a_visible_window_under_cdp(cdp):
    cdp()
    pw = _FakePlaywright()
    adapter = _adapter(pw, headless=False)
    with pytest.raises(CdpBrowserUnavailable, match="headless=False"):
        await adapter._launch()
    pw.chromium.launch.assert_not_awaited()


@pytest.mark.asyncio
async def test_adapter_refuses_a_proxied_config_under_cdp(cdp):
    cdp()
    pw = _FakePlaywright()
    adapter = _adapter(pw, proxy_server="http://proxy:8080")
    with pytest.raises(CdpBrowserUnavailable, match="proxy"):
        await adapter._launch()
    pw.chromium.launch.assert_not_awaited()


@pytest.mark.asyncio
async def test_adapter_launches_firefox_regardless_of_cdp(cdp):
    from weebot.application.ports.browser_port import BrowserType

    cdp()
    pw = _FakePlaywright()
    pw.firefox.launch.return_value = _live_browser()
    adapter = _adapter(pw, browser_type=BrowserType.FIREFOX)
    await adapter._launch()
    pw.firefox.launch.assert_awaited_once_with(headless=True)
    pw.chromium.connect_over_cdp.assert_not_awaited()


@pytest.mark.asyncio
async def test_adapter_proxy_reaches_a_local_launch_when_opted_in(cdp):
    cdp(fallback=True)
    pw = _FakePlaywright()
    pw.chromium.launch.return_value = _live_browser()
    adapter = _adapter(pw, proxy_server="http://proxy:8080")
    await adapter._launch()
    pw.chromium.launch.assert_awaited_once_with(
        headless=True, proxy={"server": "http://proxy:8080"}
    )


@pytest.mark.asyncio
async def test_pool_session_goes_through_the_launcher(cdp):
    from weebot.application.ports.browser_port import BrowserConfig
    from weebot.infrastructure.browser.session_pool import BrowserSessionPool

    cdp()
    pw = _FakePlaywright()
    pw.chromium.connect_over_cdp.return_value = _live_browser()
    pool = BrowserSessionPool()
    pool._playwright = pw
    session = await pool._create_session(BrowserConfig())
    assert session.page is not None
    pw.chromium.launch.assert_not_awaited()

    with pytest.raises(CdpBrowserUnavailable):
        await pool._create_session(BrowserConfig(headless=False))
    assert pool._stats["errors"] == 1


@pytest.mark.asyncio
async def test_web_scraper_reports_a_refusal_as_a_tool_error(cdp, monkeypatch):
    import contextlib

    import playwright.async_api as pwapi

    from weebot.tools.advanced_browser import WebScraperTool

    cdp()
    pw = _FakePlaywright(connect_error=ConnectionRefusedError("refused"))

    @contextlib.asynccontextmanager
    async def fake_async_playwright():
        yield pw

    monkeypatch.setattr(pwapi, "async_playwright", fake_async_playwright)
    result = await WebScraperTool().execute(url="https://example.com", selector="h1")
    assert result.error and "unavailable" in result.error
    pw.chromium.launch.assert_not_awaited()


# --- pool cap ------------------------------------------------------------------------------


def _cap(monkeypatch, url, limit):
    from weebot.config.settings import get_settings

    monkeypatch.setattr(get_settings(), "browser_cdp_url", url, raising=False)
    monkeypatch.setattr(get_settings(), "browser_cdp_max_connections", limit, raising=False)


def test_pool_is_clamped_to_the_cdp_connection_limit(monkeypatch):
    from weebot.infrastructure.browser.session_pool import BrowserSessionPool

    _cap(monkeypatch, URL, 2)
    pool = BrowserSessionPool(min_sessions=3, max_sessions=5)
    assert (pool.min_sessions, pool.max_sessions) == (2, 2)
    assert pool._semaphore._value == 2


@pytest.mark.parametrize(("url", "limit"), [(None, 2), (URL, 0), (URL, 9)])
def test_pool_is_untouched_without_a_cap(monkeypatch, url, limit):
    from weebot.infrastructure.browser.session_pool import BrowserSessionPool

    _cap(monkeypatch, url, limit)
    pool = BrowserSessionPool(min_sessions=1, max_sessions=5)
    assert (pool.min_sessions, pool.max_sessions) == (1, 5)
