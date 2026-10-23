"""An ASK a human approved runs the command; it is not refused a second time.

GuardedTool sent ExecApprovalPolicy's ASK to the approval channel, then ran the
inner shell tool, which evaluated the same policy and refused
`requires_confirmation` ("requires user confirmation"). So no shell approval,
from the terminal or the web UI, ever ran (Wave G tools card, defect 1).
The existing approval tests use a recorder as the inner tool, so they missed it.
"""

from __future__ import annotations

from types import SimpleNamespace

from weebot.application.ports.approval_port import ApprovalOutcome
from weebot.application.services.tool_approval import DenyApproval
from weebot.application.services.tool_guards import GuardedTool, default_guard_chain
from weebot.tools.bash_tool import BashTool

_CMD = "rm -rf build"  # ExecApprovalPolicy: approved, requires_confirmation


class _Sandbox:
    def __init__(self):
        self.scripts = []

    async def execute_shell(self, script, **kw):
        self.scripts.append(script)
        return SimpleNamespace(
            timed_out=False, success=True, stdout="", stderr="", returncode=0,
            combined_output="done",
        )


class _Answer(DenyApproval):
    def __init__(self, outcome):
        self.outcome = outcome

    async def resolve(self, request):
        return self.outcome


def _wrapped(outcome):
    sandbox = _Sandbox()
    tool = GuardedTool.wrap(
        BashTool(sandbox=sandbox), default_guard_chain(), "enforce", _Answer(outcome)
    )
    return sandbox, tool


async def test_an_approved_ask_reaches_the_sandbox():
    sandbox, tool = _wrapped(ApprovalOutcome.APPROVED)
    result = await tool.execute(command=_CMD)
    assert not result.is_error, result.error
    assert sandbox.scripts == [_CMD]


async def test_a_denied_ask_does_not():
    sandbox, tool = _wrapped(ApprovalOutcome.DENIED)
    result = await tool.execute(command=_CMD)
    assert result.is_error and sandbox.scripts == []


async def test_the_bare_tool_still_refuses_without_a_human():
    sandbox = _Sandbox()
    result = await BashTool(sandbox=sandbox).execute(command=_CMD)
    assert result.is_error and sandbox.scripts == []


_PY = 'import subprocess; subprocess.run(["rm", "-rf", "build"])'  # requires confirmation


class _PySandbox:
    def __init__(self):
        self.codes = []

    async def execute_python(self, code, **kw):
        self.codes.append(code)
        return SimpleNamespace(
            timed_out=False, success=True, stdout="ok", stderr="", returncode=0,
            combined_output="ok",
        )


async def test_python_execute_gets_the_same_approval_route():
    from weebot.tools.python_tool import PythonExecuteTool

    sandbox = _PySandbox()
    tool = GuardedTool.wrap(
        PythonExecuteTool(sandbox=sandbox),
        default_guard_chain(),
        "enforce",
        _Answer(ApprovalOutcome.APPROVED),
    )
    result = await tool.execute(code=_PY)
    assert not result.is_error, result.error
    assert sandbox.codes == [_PY]
