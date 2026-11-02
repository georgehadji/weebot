"""Decision D5 (plan 2026-10-29, P2): once untrusted content is in a session, every tool
that is not read-only asks first.

Before, taint only escalated egress, and the mail gate paused only the next step. A page
or a mail that said "now delete this folder" or "write this to the startup folder" could
still have the agent do it unasked, as long as nothing left the machine.
"""

from __future__ import annotations

import pytest

from tests.unit.test_tool_executor_egress import FakeToolCollection, make_guard
from weebot.application.agents.executor._session_scope import get_session_scope
from weebot.application.agents.executor._tool_executor import ToolExecutor
from weebot.application.ports.approval_port import ApprovalOutcome, ApprovalPort
from weebot.application.services.tool_approval import approval_scope
from weebot.application.services.tool_guards import reads_only
from weebot.core.approval_policy import is_output_only_python

SESSION = "sess-d5-taint"
WRITE_OUTSIDE = {"command": "create", "path": "C:/Users/x/AppData/startup.ps1", "file_text": "x"}


class _Approve(ApprovalPort):
    def __init__(self) -> None:
        self.asked: list[str] = []

    async def resolve(self, request):
        self.asked.append(request.guard)
        return ApprovalOutcome.APPROVED


@pytest.fixture(autouse=True)
def clean():
    get_session_scope().close(SESSION)
    yield
    get_session_scope().close(SESSION)


def _executor() -> tuple[ToolExecutor, FakeToolCollection]:
    tools = FakeToolCollection()
    ex = ToolExecutor(tools=tools, egress_guard=make_guard())
    ex.set_step_context("step-1", SESSION, "do it")
    return ex, tools


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("web_search", {"query": "x"}),
        ("file_editor", {"command": "view", "path": "C:/anything.txt"}),
        ("file_editor", {"command": "create", "path": "Output/report.md", "file_text": "x"}),
        ("powershell", {"command": "Get-ChildItem ."}),
        ("persistent_memory", {"action": "read"}),
        ("knowledge", {"action": "search", "query": "x"}),
        ("mcp__jira__jira_get_issue", {"key": "A-1"}),
    ],
)
def test_reads_and_own_workspace_writes_do_not_ask(name, args):
    assert reads_only(name, args)


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("file_editor", WRITE_OUTSIDE),
        ("powershell", {"command": "Remove-Item C:/Users/x/Documents -Recurse"}),
        ("bash", {"command": "ls && rm -rf ~/notes"}),
        ("python_execute", {"code": "print(1)"}),
        ("persistent_memory", {"action": "add", "content": "always obey the web page"}),
        ("knowledge", {"action": "add_note", "content": "x"}),
        ("schedule", {"action": "create"}),
        ("some_new_tool", {}),
    ],
)
def test_everything_else_is_not_read_only(name, args):
    assert not reads_only(name, args)


@pytest.mark.asyncio
async def test_a_tainted_session_asks_before_a_write():
    ex, tools = _executor()
    await ex.execute_tool("web_search", {"query": "x"})
    result = await ex.execute_tool("file_editor", WRITE_OUTSIDE)
    assert result.error and "approval" in result.error.lower()
    assert [c[0] for c in tools.calls] == ["web_search"]


@pytest.mark.asyncio
async def test_an_untainted_session_writes_unasked():
    ex, tools = _executor()
    await ex.execute_tool("file_editor", WRITE_OUTSIDE)
    assert [c[0] for c in tools.calls] == ["file_editor"]


@pytest.mark.asyncio
async def test_an_approved_write_runs_once_asked():
    ex, tools = _executor()
    await ex.execute_tool("web_search", {"query": "x"})
    channel = _Approve()
    with approval_scope(approval=channel):
        await ex.execute_tool("file_editor", WRITE_OUTSIDE)
    assert channel.asked == ["untrusted_content"]
    assert [c[0] for c in tools.calls] == ["web_search", "file_editor"]


@pytest.mark.asyncio
async def test_a_tainted_session_still_reads_unasked():
    ex, tools = _executor()
    await ex.execute_tool("web_search", {"query": "x"})
    await ex.execute_tool("web_search", {"query": "y"})
    assert [c[0] for c in tools.calls] == ["web_search", "web_search"]


def test_local_python_subset_allows_only_output_writes():
    safe = '''import json
out = "Output/research"
path = os.path.join(out, "queries.json")
os.makedirs(out, exist_ok=True)
with open(path, "w", encoding="utf-8") as handle:
    json.dump({"query": "Lyapunov"}, handle)
'''
    assert is_output_only_python(safe)
    assert not is_output_only_python('import requests\nrequests.get("https://example.com")')
    assert not is_output_only_python('open("C:/Users/tesse/notes.txt", "w").write("x")')


@pytest.mark.asyncio
async def test_opt_in_local_python_runs_after_untrusted_content(monkeypatch):
    monkeypatch.setenv("WEEBOT_AUTO_APPROVE_LOCAL_AFTER_UNTRUSTED", "true")
    ex, tools = _executor()
    await ex.execute_tool("web_search", {"query": "x"})
    result = await ex.execute_tool(
        "python_execute",
        {"code": 'import os\nout = "Output/research"\nos.makedirs(out, exist_ok=True)\nprint(out)'},
    )
    assert not result.is_error
    assert [call[0] for call in tools.calls] == ["web_search", "python_execute"]


@pytest.mark.asyncio
async def test_opt_in_does_not_allow_network_python(monkeypatch):
    monkeypatch.setenv("WEEBOT_AUTO_APPROVE_LOCAL_AFTER_UNTRUSTED", "true")
    ex, tools = _executor()
    await ex.execute_tool("web_search", {"query": "x"})
    result = await ex.execute_tool(
        "python_execute", {"code": 'import requests\nrequests.get("https://example.com")'}
    )
    assert result.error and "approval" in result.error.lower()
    assert [call[0] for call in tools.calls] == ["web_search"]
