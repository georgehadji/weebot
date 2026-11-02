"""The dependency installer accepts only trusted catalog clients and safe argv."""

from __future__ import annotations

import sys

from weebot.config.tool_config import ToolConfig
from weebot.tools.tool_installer import ToolInstaller


class _Proc:
    returncode = 0

    async def communicate(self):
        return b"installed", b""


async def test_installer_is_disabled_by_default():
    result = await ToolInstaller().execute(source="pypi", package="requests")
    assert result.is_error and "WEEBOT_AUTO_INSTALL_TOOLS" in result.error


async def test_pypi_install_uses_the_current_python_and_safe_argv(monkeypatch):
    calls = []

    async def _exec(*argv, **_kwargs):
        calls.append(argv)
        return _Proc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", _exec)
    tool = ToolInstaller()
    tool.set_config(ToolConfig(auto_install_tools=True))
    result = await tool.execute(source="pypi", package="requests", version="2.32.3")
    assert not result.is_error
    assert calls == [
        (
            sys.executable,
            "-m",
            "pip",
            "install",
            "--user",
            "--disable-pip-version-check",
            "requests==2.32.3",
        )
    ]


async def test_unsafe_package_text_never_starts_a_process(monkeypatch):
    started = False

    async def _exec(*_args, **_kwargs):
        nonlocal started
        started = True
        return _Proc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", _exec)
    tool = ToolInstaller()
    tool.set_config(ToolConfig(auto_install_tools=True))
    result = await tool.execute(source="npm", package="good; rm -rf /")
    assert result.is_error and not started


def test_unknown_sources_and_direct_urls_are_refused():
    assert ToolInstaller._command("url", "https://example.test/a", "") is None
