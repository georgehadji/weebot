"""R12 (audit 2026-10-29): a non-zero exit is an error even when stderr is empty.

PowerShellTool reported failure only when the script both failed and wrote to stderr, so
``exit 3`` (or a native program that fails quietly) came back as a success with
"(no output)". BashTool and PythonTool had the right rule in their own copies; the three
now share one mapping.
"""

from __future__ import annotations

import pytest

from weebot.application.ports.sandbox_port import SandboxResult
from weebot.tools.powershell_tool import PowerShellTool


class _Sandbox:
    def __init__(self, result: SandboxResult) -> None:
        self.result = result

    async def execute_shell(self, **_):
        return self.result


def _run(returncode: int, stdout: str = "", stderr: str = "") -> SandboxResult:
    return SandboxResult(stdout=stdout, stderr=stderr, returncode=returncode, elapsed_ms=1.0)


@pytest.mark.asyncio
async def test_a_quiet_non_zero_exit_is_an_error():
    tool = PowerShellTool(sandbox=_Sandbox(_run(3, stdout="partial")))
    result = await tool.execute("Write-Output partial")
    assert result.error == "Exit code 3"
    assert result.output == "partial"


@pytest.mark.asyncio
async def test_a_zero_exit_with_warnings_stays_a_success():
    tool = PowerShellTool(sandbox=_Sandbox(_run(0, stdout="done", stderr="WARNING: slow")))
    result = await tool.execute("Write-Output done")
    assert not result.error
    assert "done" in result.output and "WARNING: slow" in result.output


@pytest.mark.asyncio
async def test_a_memory_kill_is_an_error():
    killed = SandboxResult(stdout="", stderr="", returncode=0, elapsed_ms=1.0, memory_killed=True)
    result = await PowerShellTool(sandbox=_Sandbox(killed)).execute("Write-Output x")
    assert result.error
