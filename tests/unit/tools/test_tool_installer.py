"""The dependency installer takes a catalog name and nothing else.

A name that is a URL, a VCS spec, a local path or a GitHub shorthand would let pip or npm
fetch and run code from anywhere, which is the one thing this tool must not do.
"""

from __future__ import annotations

import sys

import pytest

from weebot.application.services.tool_guards import is_outbound_tool
from weebot.config.settings import WeebotSettings
from weebot.config.tool_config import ToolConfig, tool_config_from_settings
from weebot.tools import tool_installer
from weebot.tools.tool_installer import ToolInstaller


class _Proc:
    returncode = 0

    async def communicate(self):
        return b"installed", b""


def _enabled() -> ToolInstaller:
    tool = ToolInstaller()
    tool.set_config(ToolConfig(auto_install_tools=True))
    return tool


def _record(monkeypatch) -> list[tuple]:
    calls: list[tuple] = []

    async def _exec(*argv, **_kwargs):
        calls.append(argv)
        return _Proc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", _exec)
    return calls


async def test_installer_can_be_turned_off(monkeypatch):
    calls = _record(monkeypatch)
    tool = ToolInstaller()
    tool.set_config(ToolConfig(auto_install_tools=False))
    result = await tool.execute(source="pypi", package="requests")
    assert result.is_error and "WEEBOT_AUTO_INSTALL_TOOLS" in result.error
    assert not calls


def test_installing_is_on_by_default_and_still_asks():
    assert WeebotSettings().auto_install_tools and ToolConfig().auto_install_tools
    assert is_outbound_tool("install_tool")


def test_the_setting_reaches_the_tool_config():
    assert tool_config_from_settings(WeebotSettings(auto_install_tools=True)).auto_install_tools


async def test_pypi_install_takes_wheels_only(monkeypatch):
    """A source distribution runs its setup.py at install time, so only wheels are allowed."""
    monkeypatch.setattr(tool_installer, "_in_virtualenv", lambda: True)
    calls = _record(monkeypatch)
    result = await _enabled().execute(source="pypi", package="requests", version="2.32.3")
    assert not result.is_error
    assert calls == [
        (
            sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
            "--only-binary=:all:", "requests==2.32.3",
        )
    ]


async def test_pypi_outside_a_virtualenv_installs_per_user(monkeypatch):
    monkeypatch.setattr(tool_installer, "_in_virtualenv", lambda: False)
    calls = _record(monkeypatch)
    await _enabled().execute(source="pypi", package="requests")
    assert "--user" in calls[0]


async def test_npm_install_skips_lifecycle_scripts(monkeypatch):
    calls = _record(monkeypatch)
    await _enabled().execute(source="npm", package="@types/node", version="22.0.0")
    argv = calls[0]
    assert "--ignore-scripts" in argv and argv[-1] == "@types/node@22.0.0"


async def test_winget_is_pinned_to_the_winget_catalog(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    calls = _record(monkeypatch)
    await _enabled().execute(source="winget", package="Git.Git")
    argv = calls[0]
    assert argv[argv.index("--source") + 1] == "winget"
    assert argv[argv.index("--id") + 1] == "Git.Git"


@pytest.mark.parametrize(
    ("source", "package"),
    [
        ("pypi", "git+https://example.test/x.git"),
        ("pypi", "https://example.test/x.whl"),
        ("pypi", "C:/Users/me/evil"),
        ("pypi", "./local"),
        ("pypi", "x; rm -rf /"),
        ("pypi", "-r"),
        ("npm", "user/repo"),
        ("npm", "github:user/repo"),
        ("npm", "https://example.test/x.tgz"),
        ("npm", "file:../evil"),
        ("npm", "good; rm -rf /"),
        ("winget", "Pub.App --source msstore"),
        ("winget", "https://example.test/setup.exe"),
    ],
)
async def test_anything_but_a_catalog_name_never_starts_a_process(monkeypatch, source, package):
    calls = _record(monkeypatch)
    result = await _enabled().execute(source=source, package=package)
    assert result.is_error
    assert not calls


@pytest.mark.parametrize("version", ["1.0 --index-url=x", "1;2", "../x", "-1"])
async def test_a_version_cannot_carry_an_option(monkeypatch, version):
    calls = _record(monkeypatch)
    result = await _enabled().execute(source="pypi", package="requests", version=version)
    assert result.is_error
    assert not calls


async def test_an_unknown_source_is_refused(monkeypatch):
    calls = _record(monkeypatch)
    result = await _enabled().execute(source="url", package="https://example.test/a")
    assert result.is_error
    assert not calls


async def test_a_failed_install_reports_the_exit_code(monkeypatch):
    class _Failing(_Proc):
        returncode = 1

    async def _exec(*_argv, **_kwargs):
        return _Failing()

    monkeypatch.setattr("asyncio.create_subprocess_exec", _exec)
    result = await _enabled().execute(source="pypi", package="requests")
    assert result.is_error and "exit 1" in result.error


def test_installing_always_asks_even_when_the_pattern_list_is_replaced(monkeypatch):
    """WEEBOT_OUTBOUND_TOOL_PATTERNS is user-editable; this tool must not depend on it."""
    monkeypatch.setenv("WEEBOT_OUTBOUND_TOOL_PATTERNS", "nothing_matches_*")
    from weebot.config import settings as settings_module

    settings_module.get_settings.cache_clear()
    try:
        assert is_outbound_tool("install_tool")
    finally:
        settings_module.get_settings.cache_clear()
