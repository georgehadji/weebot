"""Per-call sandbox network (ICM fix plan W3.9, decision 7, ADR-013 section 3)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from weebot.application.agents.executor._tool_executor import ToolExecutor
from weebot.application.ports.approval_port import ApprovalOutcome
from weebot.application.ports.sandbox_port import (
    SandboxCapability,
    SandboxConfig,
    network_allowed,
    network_cleared_for_call,
)
from weebot.application.services.tool_approval import DenyApproval, approval_scope
from weebot.core.egress_guard import EgressGuard, RecipientAllowlist
from weebot.domain.models.tool_result import ToolResult
from weebot.infrastructure.sandbox.docker_linux import DockerLinuxSandbox
from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox, _build_child_env


def test_network_is_allowed_only_inside_a_cleared_call():
    config = SandboxConfig()
    assert network_allowed(config) is False
    with network_cleared_for_call():
        assert network_allowed(config) is True
    assert network_allowed(config) is False
    assert network_allowed(SandboxConfig(allow_network=True)) is True


def test_native_proxy_block_lifts_for_a_cleared_call():
    assert _build_child_env(SandboxConfig())["HTTP_PROXY"] == "http://127.0.0.1:9"
    with network_cleared_for_call():
        assert "HTTP_PROXY" not in _build_child_env(SandboxConfig())


async def test_docker_command_is_hardened_and_network_none_unless_cleared(monkeypatch):
    sandbox = DockerLinuxSandbox(SandboxConfig())

    async def _image():
        return "img"

    monkeypatch.setattr(sandbox, "_resolve_image", _image)
    cmd = await sandbox._build_docker_command(["true"])
    assert cmd[cmd.index("--network") + 1] == "none"
    for flag, value in (("--cap-drop", "ALL"), ("--security-opt", "no-new-privileges")):
        assert cmd[cmd.index(flag) + 1] == value
    assert "--pids-limit" in cmd
    with network_cleared_for_call():
        assert "--network" not in await sandbox._build_docker_command(["true"])


def test_only_docker_claims_network_isolation():
    assert SandboxCapability.NETWORK_ISOLATION in DockerLinuxSandbox().get_capabilities()
    assert SandboxCapability.NETWORK_ISOLATION not in NativeWindowsSandbox().get_capabilities()


class _Tools:
    def __init__(self):
        self.network: list[bool] = []

    async def execute(self, _name, **kwargs):
        self.network.append(network_allowed(SandboxConfig()))
        return ToolResult(output="ok")

    def get_tool(self, name):
        return None


def _executor(known=()):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    path.write_text(json.dumps({h: 0.0 for h in known}))
    tools = _Tools()
    return ToolExecutor(tools=tools, egress_guard=EgressGuard(RecipientAllowlist(path))), tools


class _Approve(DenyApproval):
    async def resolve(self, request):
        return ApprovalOutcome.APPROVED


async def test_download_to_a_new_host_is_refused_without_a_human():
    executor, tools = _executor()
    result = await executor.execute_tool("bash", {"command": "pip install requests"})
    assert result.is_error and "pypi.org" in result.error
    assert tools.network == []


async def test_download_to_a_known_host_gets_network():
    executor, tools = _executor(known=["pypi.org"])
    await executor.execute_tool("bash", {"command": "pip install requests"})
    assert tools.network == [True]


async def test_approved_download_gets_network():
    executor, tools = _executor()
    with approval_scope(approval=_Approve()):
        await executor.execute_tool("bash", {"command": "git clone https://github.com/a/b"})
    assert tools.network == [True]


async def test_offline_command_runs_without_network():
    executor, tools = _executor()
    await executor.execute_tool("bash", {"command": "ls -la"})
    assert tools.network == [False]


async def test_allowlisted_python_egress_gets_network():
    executor, tools = _executor(known=["api.example.invalid"])
    code = "import requests\nrequests.get('https://api.example.invalid/v1')"
    await executor.execute_tool("python_execute", {"code": code})
    assert tools.network == [True]


async def test_network_on_setting_skips_the_download_gate(monkeypatch):
    monkeypatch.setenv("SANDBOX_ALLOW_NETWORK", "true")
    executor, tools = _executor()
    result = await executor.execute_tool("bash", {"command": "pip install requests"})
    assert not result.is_error
    assert tools.network == [False]  # the sandbox's own config allows it; no per-call flag


@pytest.fixture(autouse=True)
def _enforcing(monkeypatch):
    monkeypatch.delenv("WEEBOT_EGRESS_ENFORCE", raising=False)
