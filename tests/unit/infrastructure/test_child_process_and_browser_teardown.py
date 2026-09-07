"""D37 and D38 — resources acquired and then not released.

Both were generated in W4, deferred to W7, and W7 spent its budget elsewhere.
They are the same shape: a path that acquires something and a path that was
supposed to give it back.

D38 — `qmd_integration/mcp_client.py`
    `_start_mcp_http` assigned its child to a LOCAL, so `close()` could not
    reach it and every start leaked a `qmd mcp --http` holding the port. ruff
    reports that as F841; CI selects only `F821,E9`, so nothing asked.
    `close()` then called `terminate()` with no `wait()`. Measured:

        after terminate() with no wait():   Z    sleep
        after wait():                       (gone)

    One defunct entry per start/stop cycle in a long-lived agent.

D37 — `infrastructure/browser/playwright_adapter.py`
    `start()` had no failure path. A raise from `new_context` or `new_page`
    left a LIVE browser process attached to `self`, and neither caller
    (`advanced_browser.py:370`, `browser_inspector.py:283`) closes a `start()`
    that raised. `close()` was sequential, so a context that failed to close
    stranded the browser and the driver behind it.

    Found while reading it: `record_har=True` opened a page, dropped it
    unassigned, and never set `record_har_path` — so it recorded nothing and
    leaked a page per start, under a comment asserting that HAR is configured
    at context level. It is; it wasn't.
"""

from __future__ import annotations

import subprocess
import sys
import types

import pytest

from weebot.application.ports.browser_port import BrowserConfig
from weebot.core.process_lifecycle import reap_process
from weebot.infrastructure.browser.playwright_adapter import PlaywrightAdapter


# ── D38 ───────────────────────────────────────────────────────────────


def _sleeper(tmp_path) -> str:
    """A stand-in for `qmd` that ignores its arguments and stays alive."""
    script = tmp_path / "fake_qmd"
    script.write_text("#!/bin/sh\nexec sleep 30\n")
    script.chmod(0o755)
    return str(script)


def test_reap_collects_the_child_instead_of_leaving_it_defunct():
    """`terminate()` alone leaves state Z until the parent exits.

    CONTRACT TEST for the new helper, not a red-before-green case for the
    defect — `reap_process` did not exist before, so nothing here could fail
    against the old code. The defect itself is pinned by
    `test_the_http_server_is_reachable_by_close`. What this holds is the
    premise the fix rests on, asserted rather than assumed: the first
    assertion below fails if `terminate()` ever starts reaping on its own.
    """
    proc = subprocess.Popen(["sleep", "30"])

    proc.terminate()
    proc.poll()
    assert proc.returncode is None, "terminate() alone does not reap — the premise"

    code = reap_process(proc)
    assert code is not None, "the child was still unreaped after reap_process"
    assert proc.poll() is not None


def test_reap_escalates_when_sigterm_is_ignored():
    """A child that traps SIGTERM must not hold shutdown open forever.

    CONTRACT TEST, as above. It matters because the escalation is the part a
    reaper is most likely to be written without.
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", "import signal,time\n"
         "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
         "time.sleep(60)"]
    )
    try:
        code = reap_process(proc, timeout=1.0)
        assert code is not None, "SIGKILL escalation did not happen"
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:  # pragma: no cover - belt and braces
            proc.kill()
            proc.wait()


@pytest.mark.asyncio
async def test_the_http_server_is_reachable_by_close(tmp_path, monkeypatch):
    """The defect in one assertion: `close()` could not see the child.

    `proc = subprocess.Popen(...)` bound a local. Nothing else in the class
    referenced it, so the server outlived the client that started it.
    """
    from weebot.qmd_integration import mcp_client as mod

    monkeypatch.setattr(mod.QMDMCPClient, "_check_qmd", lambda self: True)
    monkeypatch.setattr(mod.asyncio, "sleep", _instant_sleep)

    client = mod.QMDMCPClient(qmd_path=_sleeper(tmp_path), transport="http")
    await client._start_mcp_http()

    proc = client._http_process
    assert proc is not None, "the HTTP server was not reachable from the client"
    assert proc.poll() is None, "the stand-in server should still be running"

    client.close()
    assert proc.poll() is not None, "close() left the HTTP server running"
    assert client._http_process is None


@pytest.mark.asyncio
async def test_starting_twice_does_not_start_a_second_server(tmp_path, monkeypatch):
    """Without the handle there was nothing to check, so every call started one."""
    from weebot.qmd_integration import mcp_client as mod

    monkeypatch.setattr(mod.QMDMCPClient, "_check_qmd", lambda self: True)
    monkeypatch.setattr(mod.asyncio, "sleep", _instant_sleep)

    client = mod.QMDMCPClient(qmd_path=_sleeper(tmp_path), transport="http")
    try:
        await client._start_mcp_http()
        first = client._http_process
        await client._start_mcp_http()
        assert client._http_process is first, "a second server was started"
    finally:
        client.close()


async def _instant_sleep(_seconds):
    """The real `_start_mcp_http` waits 2s for the server; the wait is not
    under test and it is paid on every run."""
    return None


# ── D37 ───────────────────────────────────────────────────────────────


class _FakeBrowser:
    def __init__(self, context):
        self._context = context
        self.closed = False

    async def new_context(self, **_options):
        if isinstance(self._context, Exception):
            raise self._context
        return self._context

    async def close(self):
        self.closed = True


class _FakeContext:
    def __init__(self, page_error=None):
        self._page_error = page_error
        self.closed = False
        self.pages_opened = 0
        self.options: dict = {}

    async def new_page(self):
        if self._page_error is not None:
            raise self._page_error
        self.pages_opened += 1
        return object()

    async def close(self):
        self.closed = True


class _FakeDriver:
    def __init__(self, browser):
        self.chromium = types.SimpleNamespace(launch=self._launch)
        self.firefox = self.chromium
        self.webkit = self.chromium
        self._browser = browser
        self.stopped = False

    async def _launch(self, **_options):
        return self._browser

    async def stop(self):
        self.stopped = True


def _install_fake_playwright(monkeypatch, driver) -> None:
    """`start()` imports `playwright.async_api` inside the function.

    Patching the adapter module would miss it; the import has to be satisfied
    from `sys.modules` at call time.
    """

    class _Launcher:
        async def start(self):
            return driver

    module = types.ModuleType("playwright.async_api")
    module.async_playwright = lambda: _Launcher()
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)


@pytest.mark.asyncio
async def test_a_failed_start_does_not_strand_a_live_browser(monkeypatch):
    """The defect: `new_context` raises, the browser process keeps running.

    Neither caller closes a `start()` that raised, so nothing else would.
    """
    browser = _FakeBrowser(context=RuntimeError("no context for you"))
    driver = _FakeDriver(browser)
    _install_fake_playwright(monkeypatch, driver)

    adapter = PlaywrightAdapter()
    with pytest.raises(RuntimeError, match="no context"):
        await adapter.start(BrowserConfig(headless=True))

    assert browser.closed, "the browser process was left running"
    assert driver.stopped, "the Playwright driver was left running"
    assert adapter._browser is None
    assert adapter._playwright is None


@pytest.mark.asyncio
async def test_a_failure_closing_the_context_still_closes_the_browser(monkeypatch):
    """Sequential teardown let one stuck page strand the whole tree."""

    class _StuckContext(_FakeContext):
        async def close(self):
            raise RuntimeError("context refuses to close")

    context = _StuckContext()
    browser = _FakeBrowser(context=context)
    driver = _FakeDriver(browser)
    _install_fake_playwright(monkeypatch, driver)

    adapter = PlaywrightAdapter()
    await adapter.start(BrowserConfig(headless=True))
    await adapter.close()

    assert browser.closed, "a stuck context stranded the browser process"
    assert driver.stopped, "a stuck context stranded the Playwright driver"


@pytest.mark.asyncio
async def test_record_har_configures_har_instead_of_leaking_a_page(monkeypatch, tmp_path):
    """`record_har=True` opened a page, discarded it, and recorded nothing."""
    monkeypatch.chdir(tmp_path)
    context = _FakeContext()
    browser = _FakeBrowser(context=context)

    seen: dict = {}

    async def _new_context(**options):
        seen.update(options)
        return context

    browser.new_context = _new_context
    driver = _FakeDriver(browser)
    _install_fake_playwright(monkeypatch, driver)

    adapter = PlaywrightAdapter()
    await adapter.start(BrowserConfig(headless=True, record_har=True))

    assert "record_har_path" in seen, "record_har set no context option at all"
    assert seen["record_har_path"].endswith(".har")
    assert context.pages_opened == 1, (
        f"one page for the session, not {context.pages_opened} — the extra one leaked"
    )
