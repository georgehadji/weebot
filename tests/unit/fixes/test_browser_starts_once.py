"""Two concurrent PlaywrightAdapter.start() calls launch one browser (F73).

advanced_browser and browser_inspector share one adapter but hold separate
per-tool semaphores, so both could call start() at once; it had no lock and no
running check, and the second launch overwrote the first without closing it.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from weebot.infrastructure.browser.playwright_adapter import PlaywrightAdapter


async def test_concurrent_starts_launch_once():
    launches = []

    async def _launch(self):
        launches.append(1)
        await asyncio.sleep(0.01)
        self._browser = object()
        self._page = object()

    pw = MagicMock()
    pw.start = AsyncMock(return_value=MagicMock())
    with patch("playwright.async_api.async_playwright", return_value=pw), patch.object(
        PlaywrightAdapter, "_launch", _launch
    ):
        adapter = PlaywrightAdapter()
        await asyncio.gather(adapter.start(), adapter.start())
    assert len(launches) == 1
