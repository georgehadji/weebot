"""F12: the post_bash_guard hook payload marks DANGEROUS as needing approval.

It used to set `requires_approval` only for SUSPICIOUS. Fixed in W1.7; see
tasks/icm_fix_plan.md. This changes the payload only: the bash tool still
logs DANGEROUS and runs it until W3.7 enforces "ask" (decision 1).
"""

import asyncio

import pytest

from weebot.application.ports.sandbox_port import SandboxResult
from weebot.core import bash_guard as bash_guard_module
from weebot.core.bash_guard import RiskLevel
from weebot.tools.bash_tool import BashTool


class _Sandbox:
    async def execute_shell(self, script, shell="bash", timeout=30.0, **_):
        return SandboxResult(stdout="", stderr="", returncode=0, elapsed_ms=0.0)

    async def execute(self, command, timeout=30.0, **_):
        return SandboxResult(stdout="", stderr="", returncode=0, elapsed_ms=0.0)


class _Hooks:
    def __init__(self):
        self.payloads: list[dict] = []

    async def execute_hooks(self, name, payload):
        self.payloads.append(payload)


@pytest.mark.parametrize(
    ("risk", "expected"),
    [
        (RiskLevel.SAFE, False),
        (RiskLevel.SUSPICIOUS, True),
        (RiskLevel.DANGEROUS, True),
    ],
)
async def test_payload_requires_approval_by_risk(monkeypatch, risk, expected):
    hooks = _Hooks()
    monkeypatch.setattr(bash_guard_module, "_bash_guard_hooks", hooks)
    tool = BashTool(sandbox=_Sandbox())
    monkeypatch.setattr(tool._bash_guard, "evaluate", lambda command: (risk, []))
    await tool.execute("echo hi")
    await asyncio.sleep(0)
    assert hooks.payloads, "hook did not fire"
    assert hooks.payloads[0]["requires_approval"] is expected
