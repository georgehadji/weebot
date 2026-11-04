"""H18c approval guardian: a model's second opinion, never on what must reach a person."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from weebot.application.ports.approval_port import ApprovalOutcome
from weebot.application.ports.guardian_port import GuardianPort, GuardianVerdict
from weebot.application.services import tool_approval
from weebot.application.services.llm_guardian import MAX_COMMAND_CHARS, LLMGuardianAdapter
from weebot.application.services.tool_approval import approval_scope
from weebot.application.services.tool_guards import (
    GuardAction,
    GuardChain,
    GuardedTool,
    GuardVerdict,
)
from weebot.core.approval_scopes import ScopedGrants
from weebot.domain.models.base_tool import BaseTool
from weebot.domain.models.tool_result import ToolResult


class _Llm:
    def __init__(self, content=None, error=None):
        self._content, self._error, self.prompts = content, error, []

    async def chat(self, messages, **_):
        self.prompts.append(messages[0]["content"])
        if self._error:
            raise self._error
        return SimpleNamespace(content=self._content)


async def _verdict(content=None, error=None, command="npm test"):
    return await LLMGuardianAdapter(_Llm(content, error)).review(command, "run the tests")


@pytest.mark.parametrize(
    ("content", "verdict"),
    [
        ('{"decision": "approve", "reason": "runs tests"}', GuardianVerdict.APPROVE),
        ('```json\n{"decision": "deny", "reason": "bad"}\n```', GuardianVerdict.DENY),
        ('{"decision": "escalate"}', GuardianVerdict.ESCALATE),
        ('{"decision": "maybe"}', GuardianVerdict.ESCALATE),
        ("sure, go ahead", GuardianVerdict.ESCALATE),
        ("", GuardianVerdict.ESCALATE),
        (None, GuardianVerdict.ESCALATE),
        ('{"reason": "no decision"}', GuardianVerdict.ESCALATE),
    ],
)
async def test_the_adapter_maps_a_reply_and_escalates_anything_unusable(content, verdict):
    assert await _verdict(content) is verdict


async def test_a_model_error_escalates():
    assert await _verdict(error=RuntimeError("down")) is GuardianVerdict.ESCALATE


async def test_a_command_too_long_to_read_whole_escalates_without_a_call():
    llm = _Llm('{"decision": "approve"}')
    long = "echo " + "x" * MAX_COMMAND_CHARS
    assert await LLMGuardianAdapter(llm).review(long, "s") is GuardianVerdict.ESCALATE
    assert llm.prompts == []


async def test_the_prompt_holds_the_command_and_the_step_only():
    llm = _Llm('{"decision": "approve"}')
    await LLMGuardianAdapter(llm).review("npm test", "run the tests")
    assert len(llm.prompts) == 1
    assert "npm test" in llm.prompts[0] and "run the tests" in llm.prompts[0]


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
        self._action, self._scopable = action, scopable

    def check(self, tool_name, args):
        return GuardVerdict(self._action, self.name, "no rule", scopable=self._scopable)


class _Channel(tool_approval.DenyApproval):
    def __init__(self, outcome=ApprovalOutcome.DENIED):
        self.outcome, self.seen = outcome, []

    async def resolve(self, request):
        self.seen.append(request)
        return self.outcome


class _Guardian(GuardianPort):
    def __init__(self, verdict):
        self.verdict, self.seen = verdict, []

    async def review(self, command, step_description):
        self.seen.append((command, step_description))
        return self.verdict


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_approval, "_SCOPES", ScopedGrants(tmp_path / "approvals.json"))

    def make(verdict, *, channel_outcome=ApprovalOutcome.DENIED, **asks):
        guardian = _Guardian(verdict)
        monkeypatch.setattr(tool_approval, "_guardian", guardian)
        inner, channel = _Recorder(), _Channel(channel_outcome)
        inner.calls = []
        tool = GuardedTool.wrap(inner, GuardChain([_Asks(**asks)]), "enforce", channel)
        return guardian, inner, channel, tool

    return make


async def _run(tool, command="npm test", *, tainted=False):
    with approval_scope(session_id="s1", tainted=tainted, step_description="run the tests"):
        return await tool.execute(command=command)


async def test_approve_runs_the_command_without_asking_a_person(setup):
    guardian, inner, channel, tool = setup(GuardianVerdict.APPROVE)
    result = await _run(tool)
    assert not result.is_error and inner.calls == [{"command": "npm test"}]
    assert channel.seen == [] and guardian.seen == [("npm test", "run the tests")]


async def test_deny_refuses_without_asking_a_person(setup):
    _, inner, channel, tool = setup(
        GuardianVerdict.DENY, channel_outcome=ApprovalOutcome.APPROVED
    )
    result = await _run(tool)
    assert result.is_error and "guardian" in result.error
    assert result.data[tool_approval.DENIAL_DATA_KEY]  # it counts toward the denial breaker
    assert inner.calls == [] and channel.seen == []


async def test_escalate_asks_the_person_as_before(setup):
    guardian, _, channel, tool = setup(
        GuardianVerdict.ESCALATE, channel_outcome=ApprovalOutcome.APPROVED
    )
    assert not (await _run(tool)).is_error
    assert len(channel.seen) == 1 and len(guardian.seen) == 1


@pytest.mark.parametrize(
    "why",
    ["tainted", "taint unknown", "not scopable", "compound", "floor", "covered by a scope"],
)
async def test_the_guardian_is_never_asked(setup, why):
    asks = {"scopable": False} if why == "not scopable" else {}
    if why == "floor":
        asks = {"action": GuardAction.HUMAN}
    guardian, _, _, tool = setup(
        GuardianVerdict.APPROVE, channel_outcome=ApprovalOutcome.APPROVED, **asks
    )
    command = "npm test && npm publish" if why == "compound" else "npm test"
    if why == "covered by a scope":
        tool_approval.scope_store().grant("session", "s1", "npm test")
    if why == "taint unknown":
        with approval_scope(session_id="s1"):
            await tool.execute(command=command)
    else:
        await _run(tool, command, tainted=(why == "tainted"))
    assert guardian.seen == []
