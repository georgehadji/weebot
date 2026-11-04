"""H18b approval scopes: a yes that covers a kind of command, never a dangerous one."""

from __future__ import annotations

import json

import pytest

from weebot.application.ports.approval_port import ApprovalOutcome, ToolCallApproval
from weebot.application.services import tool_approval
from weebot.application.services.tool_approval import (
    APPROVAL_DATA_KEY,
    ConsoleApproval,
    FlowPauseApproval,
    approval_scope,
    record_flow_reply,
)
from weebot.application.services.tool_guards import (
    GuardAction,
    GuardChain,
    GuardedTool,
    GuardVerdict,
)
from weebot.core.approval import ApprovalManager
from weebot.core.approval_scopes import ScopedGrants, command_pattern
from weebot.domain.models.base_tool import BaseTool
from weebot.domain.models.tool_result import ToolResult

APPROVE = frozenset({"yes", "y"})


@pytest.mark.parametrize(
    ("command", "pattern"),
    [
        ("npm test", "npm test"),
        ("npm test --silent --coverage", "npm test --coverage --silent"),
        ("git push origin main", "git push"),
        ("git push --force-with-lease=x origin", "git push --force-with-lease"),
        ("C:\\tools\\Python.exe -m pytest", None),
        ("C:\\tools\\Python.exe --version", "python --version"),
        ("rm -rf build", None),
        ("pytest", "pytest"),
        ("npm test; rm -rf x", None),
        ("npm test && npm publish", None),
        ("echo $(whoami)", None),
        ("cat a > b", None),
        ("", None),
    ],
)
def test_command_pattern(command, pattern):
    assert command_pattern(command) == pattern


def test_session_scope_is_per_session_and_always_survives_a_restart(tmp_path):
    path = tmp_path / "approvals.json"
    scopes = ScopedGrants(path)
    scopes.grant("session", "s1", "npm test")
    scopes.grant("always", "s1", "ruff check")
    assert scopes.allows("s1", "npm test") == "session"
    assert scopes.allows("s2", "npm test") is None
    assert scopes.allows("s2", "ruff check") == "always"
    assert json.loads(path.read_text(encoding="utf-8")) == {"always": ["ruff check"]}
    assert ScopedGrants(path).allows("s9", "ruff check") == "always"


def test_a_broken_approvals_file_grants_nothing(tmp_path):
    path = tmp_path / "approvals.json"
    path.write_text("{not json", encoding="utf-8")
    assert ScopedGrants(path).allows("s1", "npm test") is None


class _Recorder(BaseTool):
    name: str = "bash"
    description: str = "records"
    parameters: dict = {"type": "object", "properties": {}}
    calls: list = []

    async def execute(self, **kwargs) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(output="ran")


class _Asks:
    name = "exec_approval_policy"

    def __init__(self, action=GuardAction.ASK, scopable=True):
        self._action = action
        self._scopable = scopable

    def check(self, tool_name, args):
        return GuardVerdict(self._action, self.name, "no rule", scopable=self._scopable)


@pytest.fixture
def scopes(tmp_path, monkeypatch):
    store = ScopedGrants(tmp_path / "approvals.json")
    monkeypatch.setattr(tool_approval, "_SCOPES", store)
    monkeypatch.setattr(tool_approval, "_GRANTS", ApprovalManager())
    return store


def _tool(approval=None, **verdict):
    inner = _Recorder()
    inner.calls = []
    approval = approval or FlowPauseApproval(ApprovalManager())
    return inner, GuardedTool.wrap(inner, GuardChain([_Asks(**verdict)]), "enforce", approval)


async def _run(tool, command, session="s1"):
    with approval_scope(session_id=session):
        return await tool.execute(command=command)


def _pending(result):
    return result.data[APPROVAL_DATA_KEY]


async def test_session_scope_allows_the_next_npm_test_but_not_npm_publish(scopes):
    inner, tool = _tool()
    pending = _pending(await _run(tool, "npm test"))
    assert pending["pattern"] == "npm test" and "'session'" in pending["prompt"]

    assert record_flow_reply("s1", pending, "session", approve_tokens=APPROVE)
    for _ in range(3):  # the first re-run spends the one-off grant; the rest ride the scope
        assert not (await _run(tool, "npm test")).is_error
    assert len(inner.calls) == 3

    assert _pending(await _run(tool, "npm publish"))["pattern"] == "npm publish"
    assert _pending(await _run(tool, "npm test --silent"))["pattern"] == "npm test --silent"
    assert len(inner.calls) == 3


async def test_a_scope_does_not_cross_sessions(scopes):
    _, tool = _tool()
    record_flow_reply("s1", _pending(await _run(tool, "npm test")), "session", approve_tokens=APPROVE)
    assert _pending(await _run(tool, "npm test", session="s2"))["pattern"] == "npm test"


async def test_a_command_that_is_not_scopable_carries_no_pattern(scopes):
    _, tool = _tool(scopable=False)
    pending = _pending(await _run(tool, "npm test"))
    assert pending["pattern"] is None
    assert not record_flow_reply("s1", pending, "session", approve_tokens=APPROVE)
    assert not record_flow_reply("s1", pending, "always", approve_tokens=APPROVE)
    assert scopes.allows("s1", "npm test") is None


async def test_a_compound_command_carries_no_pattern(scopes):
    _, tool = _tool()
    assert _pending(await _run(tool, "npm test && npm publish"))["pattern"] is None


async def test_a_floor_carries_no_pattern(scopes):
    _, tool = _tool(action=GuardAction.HUMAN)
    pending = _pending(await _run(tool, "npm test"))
    assert pending["pattern"] is None and pending["human_only"]


async def test_console_session_answer_scopes_the_pattern(scopes):
    answers = iter(["s"])

    async def ask(_prompt):
        return next(answers)  # a second prompt would raise StopIteration

    inner, tool = _tool(approval=ConsoleApproval(ask))
    assert not (await _run(tool, "npm test")).is_error
    assert not (await _run(tool, "npm test")).is_error
    assert scopes.allows("s1", "npm test") == "session"
    assert len(inner.calls) == 2


async def test_flow_pause_approves_a_covered_pattern_without_pausing(scopes):
    pause = FlowPauseApproval(ApprovalManager())
    request = ToolCallApproval("s1", "bash", {"command": "npm test"}, "fp", "g", "r", pattern="npm test")
    assert await pause.resolve(request) is ApprovalOutcome.PENDING
    scopes.grant("session", "s1", "npm test")
    assert await pause.resolve(request) is ApprovalOutcome.APPROVED
