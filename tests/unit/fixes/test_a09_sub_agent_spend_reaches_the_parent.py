"""A09: a sub-agent's spend was counted under its own session id, so the parent's
total, its soft limit and its hard limit never saw it."""

from __future__ import annotations

from weebot.application.services.session_cost import SessionCostMeter
from weebot.core.log_context import session_id_var
from weebot.domain.models.sub_agent import SubAgentSpec, SubAgentStatus
from weebot.infrastructure.adapters.sub_agent_cost_tracker import SubAgentCostTracker
from weebot.infrastructure.adapters.sub_agent_factory import SubAgentFactory


class _SpendingFlow:
    """Stands in for a PlanActFlow whose executor reported one paid call."""

    def __init__(self, meter: SessionCostMeter, session_id: str, usd: float) -> None:
        self._meter, self._session_id, self._usd = meter, session_id, usd

    async def run(self, _prompt):
        self._meter.add(self._session_id, self._usd)  # what on_domain_event does
        return
        yield  # an async generator


def _factory(meter: SessionCostMeter, usd: float):
    tracker = SubAgentCostTracker(budget_usd=10.0)
    factory = SubAgentFactory(
        llm=None,
        tools=None,
        cost_tracker=tracker,
        flow_factory=lambda session, _spec, _llm, _tools: _SpendingFlow(meter, session.id, usd),
        cost_meter=meter,
    )
    return factory, tracker


def _spec():
    return SubAgentSpec(description="d", prompt="p")


async def test_a_child_that_spends_moves_the_parent_total():
    meter = SessionCostMeter(hard_usd=1.0)
    factory, _ = _factory(meter, 1.50)
    token = session_id_var.set("parent-1")
    try:
        result = await factory.spawn(_spec())
    finally:
        session_id_var.reset(token)
    assert result.status is SubAgentStatus.COMPLETED
    assert meter.total("parent-1") == 1.50


async def test_the_child_is_recorded_at_its_own_spend_not_zero():
    meter = SessionCostMeter()
    meter.add("parent-1", 4.0)  # the parent had already spent; the child's share is 1.50
    factory, tracker = _factory(meter, 1.50)
    token = session_id_var.set("parent-1")
    try:
        await factory.spawn(_spec())
    finally:
        session_id_var.reset(token)
    assert tracker.summary()["total_spent_usd"] == 1.50


async def test_without_a_meter_the_factory_still_runs():
    tracker = SubAgentCostTracker(budget_usd=10.0)
    factory = SubAgentFactory(
        llm=None,
        tools=None,
        cost_tracker=tracker,
        flow_factory=lambda s, _sp, _l, _t: _SpendingFlow(SessionCostMeter(), s.id, 0.0),
    )
    result = await factory.spawn(_spec())
    assert result.status is SubAgentStatus.COMPLETED


def test_the_container_gives_the_factory_the_shared_meter():
    from weebot.application.di import Container
    from weebot.application.di.keys import SESSION_COST_METER
    from weebot.application.ports.sub_agent_factory_port import SubAgentFactoryPort

    container = Container()
    container.configure_defaults()
    assert container.get(SubAgentFactoryPort)._cost_meter is container.get(SESSION_COST_METER)
