"""F15: Reasoner, Berb and Scraper dirs have no developer-machine default.

They used to default to `E:\\Documents\\Vibe-Coding\\...`. With the variable
unset, each tool must refuse its CLI path with an error naming the variable,
never spawn a process (a `cwd=None` subprocess would run in the current
directory). Fixed in W1.4; see tasks/icm_fix_plan.md.
"""

import asyncio

import httpx
import pytest

from weebot.config.settings import WeebotSettings
from weebot.tools.berb import BerbTool
from weebot.tools.reasoner import ReasonerTool
from weebot.tools.scraper import ScraperTool


def test_settings_have_no_machine_specific_defaults():
    settings = WeebotSettings()
    assert (settings.reasoner_dir, settings.berb_dir, settings.scraper_dir) == (None, None, None)


@pytest.mark.parametrize(
    ("tool", "kwargs", "env_var"),
    [
        (BerbTool, {"topic": "t"}, "BERB_DIR"),
        (ReasonerTool, {"problem": "p"}, "REASONER_DIR"),
        (ScraperTool, {"url": "https://example.invalid"}, "SCRAPER_DIR"),
    ],
)
async def test_unset_dir_refuses_cli_without_spawning(monkeypatch, tool, kwargs, env_var):
    monkeypatch.delenv(env_var, raising=False)
    spawned = []

    async def _no_spawn(*args, **kw):
        spawned.append(kw.get("cwd"))
        raise AssertionError("subprocess spawned")

    async def _offline(*_a, **_k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _no_spawn)
    monkeypatch.setattr(httpx.AsyncClient, "get", _offline)
    monkeypatch.setattr(httpx.AsyncClient, "post", _offline)

    result = await tool().execute(**kwargs)

    assert spawned == []
    assert result.error and env_var in result.error
