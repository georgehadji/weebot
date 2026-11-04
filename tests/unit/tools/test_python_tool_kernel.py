"""python_execute keeps a session's variables through the kernel manager (H17)."""

from __future__ import annotations

import pytest

from weebot.application.ports.kernel_port import KernelResult
from weebot.application.ports.sandbox_port import (
    SandboxResult,
    SandboxType,
    network_cleared_for_call,
)
from weebot.application.services.kernel_manager import KernelRun
from weebot.core.log_context import session_id_var
from weebot.tools.python_tool import PythonExecuteTool


class FakeSandbox:
    def __init__(self, sandbox_type=SandboxType.NATIVE_WINDOWS):
        self.sandbox_type = sandbox_type
        self.one_shot: list[str] = []

    async def execute_python(self, code, timeout, memory_limit_mb=None):
        self.one_shot.append(code)
        return SandboxResult("one-shot", "", 0, 1.0)


class FakeKernels:
    def __init__(self, run=None, error=None):
        self.calls: list[tuple] = []
        self._run = run or KernelRun(KernelResult(stdout="from kernel\n"))
        self._error = error

    async def run(self, session_id, code, timeout, *, reset=False):
        self.calls.append((session_id, code, reset))
        if self._error:
            raise self._error
        return self._run


@pytest.fixture
def session():
    token = session_id_var.set("sess-1")
    yield "sess-1"
    session_id_var.reset(token)


def _tool(kernels, sandbox=None):
    sandbox = sandbox or FakeSandbox()
    return PythonExecuteTool(sandbox=sandbox, kernels=kernels), sandbox


@pytest.mark.asyncio
async def test_a_call_runs_in_the_sessions_kernel_by_default(session):
    kernels = FakeKernels()
    tool, sandbox = _tool(kernels)

    result = await tool.execute("x = 1")

    assert result.output == "from kernel\n" and not result.is_error
    assert kernels.calls == [("sess-1", "x = 1", False)] and sandbox.one_shot == []


@pytest.mark.asyncio
async def test_reset_is_passed_through(session):
    kernels = FakeKernels()
    tool, _ = _tool(kernels)

    await tool.execute("x = 1", reset=True)

    assert kernels.calls == [("sess-1", "x = 1", True)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arrange",
    ["persistent_false", "no_session", "other_sandbox", "no_manager"],
)
async def test_these_calls_run_one_shot(arrange):
    kernels = None if arrange == "no_manager" else FakeKernels()
    sandbox = FakeSandbox(SandboxType.DOCKER_LINUX) if arrange == "other_sandbox" else FakeSandbox()
    tool, sandbox = _tool(kernels, sandbox)
    token = session_id_var.set(None if arrange == "no_session" else "sess-1")
    try:
        extra = {"persistent": False} if arrange == "persistent_false" else {}
        result = await tool.execute("print(1)", **extra)
    finally:
        session_id_var.reset(token)

    assert sandbox.one_shot == ["print(1)"] and result.output
    assert kernels is None or kernels.calls == []


@pytest.mark.asyncio
async def test_a_call_cleared_for_the_network_runs_one_shot(session):
    kernels = FakeKernels()
    tool, sandbox = _tool(kernels)

    with network_cleared_for_call():
        await tool.execute("import urllib.request")

    assert sandbox.one_shot == ["import urllib.request"] and kernels.calls == []


@pytest.mark.asyncio
async def test_blocked_code_never_reaches_the_kernel(session):
    kernels = FakeKernels()
    tool, sandbox = _tool(kernels)

    result = await tool.execute("import os; os.system('rm -rf /')")

    assert result.is_error and "BashGuard" in result.error
    assert kernels.calls == [] and sandbox.one_shot == []


@pytest.mark.asyncio
async def test_a_traceback_is_an_error_and_keeps_the_output(session):
    run = KernelRun(KernelResult(stdout="partial\n", error="Traceback...\nValueError: no\n"))
    tool, _ = _tool(FakeKernels(run=run))

    result = await tool.execute("raise ValueError('no')")

    assert result.is_error and "ValueError" in result.error and result.output == "partial\n"


@pytest.mark.asyncio
async def test_a_dead_kernel_is_an_error(session):
    run = KernelRun(KernelResult(error="Timed out after 5s; the kernel was stopped.", died=True))
    tool, _ = _tool(FakeKernels(run=run))

    result = await tool.execute("while True: pass")

    assert result.is_error and "Timed out" in result.error


@pytest.mark.asyncio
async def test_the_model_is_told_when_its_variables_were_lost(session):
    run = KernelRun(KernelResult(stdout="3\n"), notice="its kernel was stopped to make room")
    tool, _ = _tool(FakeKernels(run=run))

    result = await tool.execute("print(1 + 2)")

    assert result.output.startswith("(Python session restarted, earlier variables are gone")
    assert "make room" in result.output and result.output.endswith("3\n")


@pytest.mark.asyncio
async def test_no_kernel_available_falls_back_to_one_shot(session):
    kernels = FakeKernels(error=RuntimeError("All 4 kernels are busy; try again shortly."))
    tool, sandbox = _tool(kernels)

    result = await tool.execute("print(1)")

    assert sandbox.one_shot == ["print(1)"] and not result.is_error
