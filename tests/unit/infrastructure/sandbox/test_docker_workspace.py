"""ADR-014: what the Docker sandbox can see and write.

The project folder is mounted read-only at /workspace, Output/ is the one
writable project folder, the root filesystem is read-only, code runs as uid
1000, /tmp is a tmpfs, pip has a cache volume, and only the built
weebot-tool-env image is used (no python:slim fallback).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from weebot.application.ports.sandbox_port import SandboxConfig
from weebot.infrastructure.sandbox.docker_linux import DockerLinuxSandbox


def _value(cmd: list[str], flag: str) -> list[str]:
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == flag]


@pytest.fixture
def workspace(tmp_path) -> Path:
    (tmp_path / "Output").mkdir()
    (tmp_path / "src").mkdir()
    return tmp_path


async def _cmd(config: SandboxConfig, monkeypatch, cwd=None) -> list[str]:
    sandbox = DockerLinuxSandbox(config)

    async def _image():
        return "weebot-tool-env:latest"

    monkeypatch.setattr(sandbox, "_resolve_image", _image)
    return await sandbox._build_docker_command(["true"], cwd)


async def test_workspace_is_read_only_and_output_is_writable(workspace, monkeypatch):
    cmd = await _cmd(SandboxConfig(workspace_dir=workspace), monkeypatch)
    mounts = _value(cmd, "-v")
    assert f"{workspace}:/workspace:ro" in mounts
    assert f"{workspace / 'Output'}:/workspace/Output" in mounts


async def test_root_is_read_only_and_code_is_not_root(workspace, monkeypatch):
    cmd = await _cmd(SandboxConfig(workspace_dir=workspace), monkeypatch)
    assert "--read-only" in cmd
    assert _value(cmd, "--user") == ["1000:1000"]
    assert any(v.startswith("/tmp:") for v in _value(cmd, "--tmpfs"))
    assert any(v.endswith(":/home/weebot/.cache/pip") for v in _value(cmd, "-v"))


async def test_host_cwd_maps_into_the_workspace(workspace, monkeypatch):
    config = SandboxConfig(workspace_dir=workspace)
    assert _value(await _cmd(config, monkeypatch), "-w") == ["/workspace"]
    assert _value(await _cmd(config, monkeypatch, workspace / "src"), "-w") == ["/workspace/src"]
    outside = workspace.parent
    assert _value(await _cmd(config, monkeypatch, outside), "-w") == ["/workspace"]


async def test_without_a_workspace_nothing_from_the_host_is_mounted(monkeypatch):
    cmd = await _cmd(SandboxConfig(), monkeypatch)
    assert not any("/workspace" in v for v in _value(cmd, "-v"))
    assert "--read-only" in cmd


async def test_only_the_tool_image_is_used(mocker):
    sandbox = DockerLinuxSandbox()
    proc = mocker.AsyncMock()
    proc.returncode = 1  # docker image inspect weebot-tool-env:latest fails
    mocker.patch("asyncio.create_subprocess_exec", return_value=proc)
    assert await sandbox._resolve_image() is None


async def test_a_missing_image_is_a_clear_error(monkeypatch):
    sandbox = DockerLinuxSandbox()

    async def _yes():
        return True

    async def _none():
        return None

    monkeypatch.setattr(sandbox, "is_available", _yes)
    monkeypatch.setattr(sandbox, "_resolve_image", _none)
    result = await sandbox.execute(["true"])
    assert not result.success
    assert "weebot-tool-env" in result.stderr and "docker build" in result.stderr


def test_the_default_config_mounts_the_workspace(monkeypatch, tmp_path):
    from weebot.config.settings import get_settings
    from weebot.infrastructure.sandbox import factory

    monkeypatch.setattr(factory, "_workspace_root", lambda: tmp_path)
    config = factory.build_sandbox_config(get_settings())
    assert config.workspace_dir == tmp_path
