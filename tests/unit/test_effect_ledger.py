"""ORCH-2: a retried flow does not repeat an outbound action it already took.

Plan item 2.2 of tasks/specs/arch_audit_2026_10_remediation_plan.md. The executor
under test is built with the real ledger over an in-memory event store; each
"retry" is a NEW ToolExecutor, as ExecuteStepHandler builds one per step.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from weebot.application.agents.executor import _tool_executor as executor_module
from weebot.application.agents.executor._tool_executor import ToolExecutor
from weebot.application.ports.event_store_port import EventStorePort
from weebot.application.services.effect_ledger import EffectLedger
from weebot.core.effect_key import effect_key, step_scope
from weebot.core.egress_guard import EgressGuard, RecipientAllowlist
from weebot.domain.models.output_trust import OutputTrust
from weebot.domain.models.tool_result import ToolResult

SEND = {"command": "curl -d 'status=ok' https://api.example.com/notify"}
SESSION = "sess-ledger"


class MemoryEventStore(EventStorePort):
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def log_event(self, session_id, event_type, data, cost=0.0, model="", tokens_used=0):
        self.rows.append({"session_id": session_id, "event_type": event_type, "data": data})
        return len(self.rows)

    async def get_session_events(self, session_id, event_type=None):
        return [
            r for r in self.rows
            if r["session_id"] == session_id and (event_type is None or r["event_type"] == event_type)
        ]

    async def count_events(self, session_ids):  # pragma: no cover - unused
        return {sid: sum(r["session_id"] == sid for r in self.rows) for sid in session_ids}

    async def get_cost_summary(self, session_id):  # pragma: no cover - unused
        return {}

    async def get_cost_window(self, window_hours):  # pragma: no cover - unused
        return {}

    async def query_recent_events(self, event_type=None, limit=50):  # pragma: no cover
        return []

    async def delete_session(self, session_id):  # pragma: no cover - unused
        return False


class FakeTools:
    """Counts real executions; get_tool returns None (unregistered)."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._fail = fail

    async def execute(self, _name: str, **kwargs):
        self.calls.append((_name, kwargs))
        if self._fail:
            return ToolResult.error_result(error="smtp down", output="")
        return ToolResult(output="sent")

    def get_tool(self, name):
        # Declared LOCAL like the real bash/python tools, so a send does not taint
        # the session and block the next one (an undeclared tool would, by design).
        return SimpleNamespace(output_trust=OutputTrust.LOCAL)


def _guard(approved: bool = True) -> EgressGuard:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    path.write_text(json.dumps({"api.example.com": 0.0} if approved else {}))
    return EgressGuard(allowlist=RecipientAllowlist(path))


def _executor(store, tools=None, step="step-2", description="Send the weekly report", guard=None):
    tools = tools or FakeTools()
    ex = ToolExecutor(tools=tools, egress_guard=guard or _guard(), effect_ledger=EffectLedger(store))
    ex.set_step_context(step, SESSION, description)
    return ex, tools


class TestRetriedFlowDoesNotResend:
    @pytest.mark.asyncio
    async def test_the_second_identical_send_is_replayed_not_executed(self):
        store = MemoryEventStore()
        first, tools = _executor(store)
        assert (await first.execute_tool("bash", dict(SEND))).output == "sent"

        retry, retry_tools = _executor(store)  # a fresh executor, as after a session retry
        result = await retry.execute_tool("bash", dict(SEND))

        assert tools.calls and retry_tools.calls == [], "the retry must not reach the tool"
        assert result.metadata["replayed"] is True and not result.is_error
        assert "Not repeated" in result.output
        assert [r["event_type"] for r in store.rows] == ["effect_recorded", "effect_replayed"]

    @pytest.mark.asyncio
    async def test_different_arguments_execute(self):
        store = MemoryEventStore()
        first, _ = _executor(store)
        await first.execute_tool("bash", dict(SEND))
        other, tools = _executor(store)
        await other.execute_tool("bash", {"command": SEND["command"].replace("ok", "different")})
        assert len(tools.calls) == 1

    @pytest.mark.asyncio
    async def test_a_re_planned_step_with_a_new_description_executes(self):
        store = MemoryEventStore()
        first, _ = _executor(store)
        await first.execute_tool("bash", dict(SEND))
        replanned, tools = _executor(store, description="Send the corrected weekly report")
        await replanned.execute_tool("bash", dict(SEND))
        assert len(tools.calls) == 1, "the user changed the plan; the send is a new intent"

    @pytest.mark.asyncio
    async def test_another_session_is_independent(self):
        store = MemoryEventStore()
        first, _ = _executor(store)
        await first.execute_tool("bash", dict(SEND))
        other, tools = _executor(store)
        other.set_step_context("step-2", "another-session", "Send the weekly report")
        await other.execute_tool("bash", dict(SEND))
        assert len(tools.calls) == 1

    @pytest.mark.asyncio
    async def test_a_non_egress_tool_is_never_ledgered(self):
        store = MemoryEventStore()
        first, _ = _executor(store)
        await first.execute_tool("python_execute", {"code": "1+1"})
        again, tools = _executor(store)
        await again.execute_tool("python_execute", {"code": "1+1"})
        assert len(tools.calls) == 1 and store.rows == []

    @pytest.mark.asyncio
    async def test_a_failed_send_is_not_recorded_so_the_retry_goes_ahead(self):
        store = MemoryEventStore()
        failing, _ = _executor(store, tools=FakeTools(fail=True))
        assert (await failing.execute_tool("bash", dict(SEND))).is_error
        assert store.rows == []
        retry, tools = _executor(store)
        await retry.execute_tool("bash", dict(SEND))
        assert len(tools.calls) == 1

    @pytest.mark.asyncio
    async def test_a_replay_never_reaches_the_approval_gate(self, monkeypatch):
        store = MemoryEventStore()
        guard = _guard(approved=False)  # unknown recipient: this send would ask
        key = effect_key(SESSION, "step-2", step_scope("Send the weekly report"), "bash", SEND)
        await EffectLedger(store).record(SESSION, key, "bash", "sent earlier", ok=True)

        async def must_not_ask(*args, **kwargs):
            raise AssertionError("a replayed action asked for approval")

        monkeypatch.setattr(executor_module, "_ask_about_egress", must_not_ask)
        ex, tools = _executor(store, guard=guard)
        result = await ex.execute_tool("bash", dict(SEND))
        assert tools.calls == [] and result.metadata["replayed"] is True

    @pytest.mark.asyncio
    async def test_an_unreadable_ledger_lets_the_call_proceed(self):
        class Broken(MemoryEventStore):
            async def get_session_events(self, *a, **k):
                raise RuntimeError("db is locked")

        ex, tools = _executor(Broken())
        await ex.execute_tool("bash", dict(SEND))
        assert len(tools.calls) == 1, "refusing a send over bookkeeping would be the worse error"


class TestTheKey:
    def test_the_key_is_stable_across_processes(self):
        """Golden value: a ledger written before a crash must be readable after it."""
        key = effect_key(
            "sess-1", "step-2", step_scope("Send the weekly report"), "atomic_mail",
            {"to": "a@b.co", "subject": "Hi", "body": "x"},
        )
        assert key == "e9593dbdad84ef39d38d740ea198d6f07033e7bf3cc8512e0d18946c7b93104a"

    def test_argument_order_does_not_change_the_key(self):
        a = effect_key("s", "1", "", "bash", {"x": 1, "y": 2})
        b = effect_key("s", "1", "", "bash", {"y": 2, "x": 1})
        assert a == b

    def test_each_component_changes_the_key(self):
        base = ("s", "1", "scope", "bash", {"x": 1})
        keys = {
            effect_key(*base),
            effect_key("s2", *base[1:]),
            effect_key(base[0], "2", *base[2:]),
            effect_key(*base[:2], "other", *base[3:]),
            effect_key(*base[:3], "powershell", base[4]),
            effect_key(*base[:4], {"x": 2}),
        }
        assert len(keys) == 6

    def test_a_blank_description_has_an_empty_scope(self):
        assert step_scope("") == ""
        assert step_scope("  a  ") == step_scope("a")
