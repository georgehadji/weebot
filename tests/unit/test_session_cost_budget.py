"""ORCH-4 / D6: a soft limit that degrades, a hard limit that asks before it stops.

Plan item 2.4 of tasks/specs/arch_audit_2026_10_remediation_plan.md.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.ports.approval_port import ApprovalOutcome, ApprovalPort
from weebot.application.services import tool_approval
from weebot.application.services.session_cost import SessionCostMeter
from weebot.application.termination.base import TerminationContext
from weebot.application.termination.conditions import SessionCostTermination
from weebot.core.log_context import log_context
from weebot.domain.models.event import LLMCallCompleted


def _call(session: str, cost: float) -> LLMCallCompleted:
    return LLMCallCompleted(session_id=session, model="m", cost=cost)


class _Bus:
    def __init__(self):
        self.events = []

    async def publish_domain_event(self, event):
        self.events.append(event)


class TestMeter:
    @pytest.mark.asyncio
    async def test_llm_call_events_accumulate_per_session(self):
        meter = SessionCostMeter(soft_usd=0.5, hard_usd=2.5)
        await meter.on_domain_event(_call("a", 0.2))
        await meter.on_domain_event(_call("a", 0.1))
        await meter.on_domain_event(_call("b", 1.0))
        assert meter.total("a") == pytest.approx(0.3) and meter.total("b") == 1.0

    @pytest.mark.asyncio
    async def test_other_events_are_ignored(self):
        meter = SessionCostMeter()
        await meter.on_domain_event(SimpleNamespace(type="fact_discovered", session_id="a", cost=9))
        assert meter.total("a") == 0

    @pytest.mark.asyncio
    async def test_crossing_the_soft_limit_emits_once(self):
        bus = _Bus()
        meter = SessionCostMeter(soft_usd=0.5, hard_usd=2.5, event_bus=bus)
        await meter.on_domain_event(_call("a", 0.4))
        assert not meter.soft_exceeded("a") and bus.events == []
        await meter.on_domain_event(_call("a", 0.2))
        await meter.on_domain_event(_call("a", 0.2))
        assert meter.soft_exceeded("a")
        [event] = bus.events
        assert event.type == "session_budget_soft_limit" and event.soft_limit_usd == 0.5

    @pytest.mark.asyncio
    async def test_sub_agent_spend_rolls_up_to_the_parent(self):
        meter = SessionCostMeter(soft_usd=0.5, hard_usd=2.5)
        meter.link("child", "parent")
        meter.link("grandchild", "child")
        await meter.on_domain_event(_call("parent", 0.1))
        await meter.on_domain_event(_call("child", 0.2))
        await meter.on_domain_event(_call("grandchild", 0.3))
        assert meter.total("parent") == pytest.approx(0.6) == meter.total("grandchild")
        assert meter.soft_exceeded("child"), "the limit is the whole tree's"

    @pytest.mark.asyncio
    async def test_resume_seeds_from_the_event_store_once(self):
        calls = []

        class Store:
            async def get_cost_summary(self, session_id):
                calls.append(session_id)
                return {"total_cost": 1.25}

        meter = SessionCostMeter(event_store=Store())
        await meter.seed("resumed")
        await meter.seed("resumed")
        assert meter.total("resumed") == 1.25 and calls == ["resumed"]

    @pytest.mark.asyncio
    async def test_an_unreadable_store_does_not_block_a_resume(self, caplog):
        class Store:
            async def get_cost_summary(self, session_id):
                raise RuntimeError("locked")

        meter = SessionCostMeter(event_store=Store())
        with caplog.at_level(logging.WARNING):
            await meter.seed("s")
        assert meter.total("s") == 0 and "could not seed" in caplog.text

    def test_zero_disables_a_threshold(self):
        meter = SessionCostMeter(soft_usd=0, hard_usd=0)
        meter.add("a", 99)
        assert not meter.soft_exceeded("a")


class TestTermination:
    def test_it_fires_at_the_allowance_and_names_budget_exceeded(self):
        cond = SessionCostTermination()
        below = cond.check(TerminationContext(session_cost_usd=2.4, session_cost_allowance_usd=2.5))
        at = cond.check(TerminationContext(session_cost_usd=2.5, session_cost_allowance_usd=2.5))
        assert not below and at and at.code == "BUDGET_EXCEEDED"

    def test_no_allowance_means_no_limit(self):
        assert not SessionCostTermination().check(TerminationContext(session_cost_usd=999))


class TestSoftLimitDegradesTheCascade:
    def _cascade(self, meter):
        return CascadeExecutor(llm=object(), tools=object(), cost_meter=meter)

    def test_premium_models_are_dropped_past_the_soft_limit(self):
        from weebot.config.model_refs import PREMIUM_MODELS

        premium = sorted(PREMIUM_MODELS)[0]
        cheap = "vendor/cheap-model"
        meter = SessionCostMeter(soft_usd=0.5)
        cascade = self._cascade(meter)
        with log_context(session_id="s"):
            assert cascade._within_budget([premium, cheap]) == [premium, cheap]
            meter.add("s", 0.6)
            assert cascade._within_budget([premium, cheap]) == [cheap]

    def test_it_never_empties_the_list(self):
        from weebot.config.model_refs import PREMIUM_MODELS

        only = sorted(PREMIUM_MODELS)[0]
        meter = SessionCostMeter(soft_usd=0.5)
        meter.add("s", 5)
        with log_context(session_id="s"):
            assert self._cascade(meter)._within_budget([only]) == [only]

    def test_without_a_meter_nothing_changes(self):
        assert self._cascade(None)._within_budget(["a", "b"]) == ["a", "b"]


class _Approval(ApprovalPort):
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []

    async def resolve(self, request):
        self.requests.append(request)
        return self.outcome


def _flow(meter, hard=None, grants=0):
    return SimpleNamespace(
        _cost_meter=meter,
        _cost_hard_override=hard,
        _budget_grants=grants,
        _session=SimpleNamespace(id="sess"),
        _log=logging.getLogger("test"),
        _pending_budget_request=None,
    )


class TestHardLimitAsks:
    @pytest.fixture
    def channel(self, monkeypatch):
        holder = {}

        def use(outcome):
            holder["port"] = _Approval(outcome)
            monkeypatch.setattr(tool_approval, "current_approval", lambda: holder["port"])
            return holder["port"]

        return use

    async def _gate(self, flow):
        from weebot.application.flows.collaborators.session_budget import budget_gate

        return await budget_gate(flow)

    @pytest.mark.asyncio
    async def test_below_the_limit_nobody_is_asked(self, channel):
        port = channel(ApprovalOutcome.DENIED)
        meter = SessionCostMeter(hard_usd=2.5)
        meter.add("sess", 2.4)
        assert (await self._gate(_flow(meter)))[0] == "ok" and port.requests == []

    @pytest.mark.asyncio
    async def test_a_headless_run_ends_as_budget_exceeded(self, channel):
        channel(ApprovalOutcome.DENIED)  # cron, webhooks, MCP: nobody can answer
        meter = SessionCostMeter(hard_usd=2.5)
        meter.add("sess", 2.6)
        gate, why = await self._gate(_flow(meter))
        assert gate == "stop" and why.startswith("BUDGET_EXCEEDED")

    @pytest.mark.asyncio
    async def test_approval_continues_for_exactly_one_increment(self, channel):
        port = channel(ApprovalOutcome.APPROVED)
        meter = SessionCostMeter(hard_usd=2.5)
        meter.add("sess", 2.6)
        flow = _flow(meter)
        assert (await self._gate(flow))[0] == "ok" and flow._budget_grants == 1
        assert (await self._gate(flow))[0] == "ok" and len(port.requests) == 1, "5.00 not reached"
        meter.add("sess", 2.5)  # now 5.1 >= 2 x 2.5
        await self._gate(flow)
        assert len(port.requests) == 2, "the next increment asks again"
        assert port.requests[0].fingerprint != port.requests[1].fingerprint

    @pytest.mark.asyncio
    async def test_a_flow_pause_returns_wait_with_the_request(self, channel):
        channel(ApprovalOutcome.PENDING)  # the web UI and gateways
        meter = SessionCostMeter(hard_usd=2.5)
        meter.add("sess", 3)
        flow = _flow(meter)
        gate, why = await self._gate(flow)
        assert gate == "wait" and "Allow it to continue" in why
        assert flow._pending_budget_request.tool_name == "session_budget"

    @pytest.mark.asyncio
    async def test_a_per_flow_override_and_zero_disable(self, channel):
        port = channel(ApprovalOutcome.DENIED)
        meter = SessionCostMeter(hard_usd=2.5)
        meter.add("sess", 10)
        assert (await self._gate(_flow(meter, hard=0)))[0] == "ok"
        assert (await self._gate(_flow(meter, hard=50)))[0] == "ok"
        assert port.requests == []
        assert (await self._gate(_flow(meter, hard=5)))[0] == "stop"
