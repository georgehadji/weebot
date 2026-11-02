"""F20: a shell or python call that fetched from the network taints the session.

`bash_tool`, `powershell_tool` and `python_tool` declare `OutputTrust.LOCAL`, and
`must_taint` fires only for EXTERNAL. So after `git clone` of an allowed host, injected
text in the cloned repo was read with no taint, and the "ask after untrusted content" rule
never fired. The executor now taints after a LOCAL call that reached the network; the tools
do not change and do not learn about taint.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from weebot.application.agents.executor._session_scope import SessionScope
from weebot.application.agents.executor._tool_executor import ToolExecutor
from weebot.core.egress_guard import EgressGuard, RecipientAllowlist
from weebot.core.trust_boundary import taints_after_network
from weebot.domain.models.output_trust import OutputTrust
from weebot.domain.models.tool_result import ToolResult

SESSION = "sess-f20"


class _Tools:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._fail = fail

    async def execute(self, _name: str, **kwargs):
        self.calls.append((_name, kwargs))
        if self._fail:
            return ToolResult.error_result(error="boom", output="")
        return ToolResult(output="ok")

    def get_tool(self, name):
        return SimpleNamespace(output_trust=OutputTrust.LOCAL)


def _executor(tmp_path, *, fail: bool = False) -> ToolExecutor:
    allowlist = RecipientAllowlist(path=tmp_path / "recipients.json")
    for host in ("github.com", "pypi.org"):
        allowlist.approve(host)
    ex = ToolExecutor(
        tools=_Tools(fail=fail),
        egress_guard=EgressGuard(allowlist),
        session_scope=SessionScope(),
    )
    ex.set_step_context("step-1", SESSION, "task")
    return ex


# ── the policy ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("trust", "is_error", "used_network", "expected"),
    [
        (OutputTrust.LOCAL, False, True, True),
        (OutputTrust.LOCAL, False, False, False),
        (OutputTrust.LOCAL, True, True, False),  # an error carries no new content
        (OutputTrust.EXTERNAL, False, True, False),  # `must_taint` already covers it
    ],
)
def test_taints_after_network_is_a_pure_table(trust, is_error, used_network, expected):
    assert taints_after_network(trust, is_error, used_network) is expected


# ── the executor ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("bash", {"command": "git clone https://github.com/x/y"}),
        ("powershell", {"command": "git clone https://github.com/x/y"}),
        ("bash", {"command": "pip install requests"}),
        ("bash", {"command": "curl https://pypi.org/simple/"}),
        ("python_execute", {"code": "import requests\nrequests.get('https://pypi.org')"}),
    ],
)
async def test_a_networked_call_taints_the_session(tmp_path, tool, args):
    ex = _executor(tmp_path)
    assert not ex._untrusted_context_active
    await ex.execute_tool(tool, dict(args))
    assert ex._untrusted_context_active, (tool, args)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("bash", {"command": "dir"}),
        ("powershell", {"command": "Get-ChildItem ."}),
        ("python_execute", {"code": "print(1 + 1)"}),
        ("bash", {"command": "git status"}),
    ],
)
async def test_a_local_call_does_not_taint(tmp_path, tool, args):
    ex = _executor(tmp_path)
    await ex.execute_tool(tool, dict(args))
    assert not ex._untrusted_context_active, (tool, args)


@pytest.mark.asyncio
async def test_a_failed_networked_call_does_not_taint(tmp_path):
    ex = _executor(tmp_path, fail=True)
    await ex.execute_tool("bash", {"command": "git clone https://github.com/x/y"})
    assert not ex._untrusted_context_active


@pytest.mark.asyncio
async def test_the_taint_outlives_the_executor_that_set_it(tmp_path):
    """One executor is built per step: the taint is per session, in the shared scope."""
    scope = SessionScope()
    allowlist = RecipientAllowlist(path=tmp_path / "r.json")
    allowlist.approve("github.com")

    def build() -> ToolExecutor:
        ex = ToolExecutor(
            tools=_Tools(), egress_guard=EgressGuard(allowlist), session_scope=scope
        )
        ex.set_step_context("step", SESSION, "task")
        return ex

    await build().execute_tool("bash", {"command": "git clone https://github.com/x/y"})
    assert build()._untrusted_context_active


@pytest.mark.asyncio
async def test_after_a_clone_a_write_outside_output_asks(tmp_path, monkeypatch):
    """The rule the taint feeds: once tainted, a call that does more than read asks (D5)."""
    from weebot.config.settings import get_settings

    monkeypatch.setattr(get_settings(), "shell_guard_mode", "enforce", raising=False)
    ex = _executor(tmp_path)
    await ex.execute_tool("bash", {"command": "git clone https://github.com/x/y"})
    tools = ex._tools
    before = len(tools.calls)

    await ex.execute_tool("file_editor", {"command": "view", "path": "y/README.md"})
    assert len(tools.calls) == before + 1, "a read still runs"

    result = await ex.execute_tool(
        "file_editor", {"command": "create", "path": str(tmp_path / "notes.md"), "file_text": "x"}
    )
    assert len(tools.calls) == before + 1, "a write outside Output/ must not run unasked"
    assert result.is_error


@pytest.mark.asyncio
async def test_a_local_dir_then_the_same_write_is_not_asked(tmp_path, monkeypatch):
    from weebot.config.settings import get_settings

    monkeypatch.setattr(get_settings(), "shell_guard_mode", "enforce", raising=False)
    ex = _executor(tmp_path)
    await ex.execute_tool("bash", {"command": "dir"})
    before = len(ex._tools.calls)
    await ex.execute_tool(
        "file_editor", {"command": "create", "path": str(tmp_path / "notes.md"), "file_text": "x"}
    )
    assert len(ex._tools.calls) == before + 1
