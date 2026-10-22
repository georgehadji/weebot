"""ADR-014 backend selection: SANDBOX_MODE=docker_first and strict isolation.

`auto` keeps its meaning (native on Windows, Docker elsewhere). `docker_first`
is the opt-in: Docker when the daemon answers and weebot-tool-env is built,
else the platform default with a warning. SANDBOX_REQUIRE_ISOLATION=true makes
a backend that cannot enforce network-off refuse sandboxed calls.
"""

from __future__ import annotations

import logging
import sys

import pytest

from weebot.infrastructure.sandbox import factory
from weebot.infrastructure.sandbox.docker_linux import DockerLinuxSandbox
from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="platform default is native")


def test_auto_is_unchanged(monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "auto")
    monkeypatch.setattr(factory, "_docker_ready", lambda: True)
    assert isinstance(factory.create_default_sandbox(), NativeWindowsSandbox)


def test_docker_first_uses_docker_when_ready(monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "docker_first")
    monkeypatch.setattr(factory, "_docker_ready", lambda: True)
    assert isinstance(factory.create_default_sandbox(), DockerLinuxSandbox)


def test_docker_first_falls_back_with_a_warning(monkeypatch, caplog):
    monkeypatch.setenv("SANDBOX_MODE", "docker_first")
    monkeypatch.setattr(factory, "_docker_ready", lambda: False)
    with caplog.at_level(logging.WARNING):
        sandbox = factory.create_default_sandbox()
    assert isinstance(sandbox, NativeWindowsSandbox)
    assert "docker_first" in caplog.text


async def test_strict_mode_refuses_on_a_backend_without_isolation(monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "native")
    monkeypatch.setenv("SANDBOX_REQUIRE_ISOLATION", "true")
    sandbox = factory.create_default_sandbox()
    result = await sandbox.execute_python("print(1)")
    assert not result.success
    assert "SANDBOX_REQUIRE_ISOLATION" in result.stderr


async def test_strict_mode_is_off_by_default(monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "native")
    assert isinstance(factory.create_default_sandbox(), NativeWindowsSandbox)


def test_strict_mode_does_not_block_a_network_on_config(monkeypatch):
    # Network is on for every call, so there is no network-off to enforce.
    monkeypatch.setenv("SANDBOX_MODE", "native")
    monkeypatch.setenv("SANDBOX_REQUIRE_ISOLATION", "true")
    monkeypatch.setenv("SANDBOX_ALLOW_NETWORK", "true")
    assert isinstance(factory.create_default_sandbox(), NativeWindowsSandbox)


def test_strict_mode_keeps_docker(monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "docker")
    monkeypatch.setenv("SANDBOX_REQUIRE_ISOLATION", "true")
    assert isinstance(factory.create_default_sandbox(), DockerLinuxSandbox)
