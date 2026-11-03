"""Delegation is bounded in depth, width, count and time, and children get scoped tools (H4)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from weebot.application.services.delegation_guard import DelegationGuard, current_depth
from weebot.application.services.tool_registry import RoleBasedToolRegistry
from weebot.domain.models.delegation import (
    SPAWN_TOOLS,
    DelegationDenied,
    DelegationPolicy,
    child_tool_names,
)
from weebot.domain.models.event import MessageEvent
from weebot.domain.models.sub_agent import SubAgentRole, SubAgentSpec, SubAgentStatus
from weebot.infrastructure.adapters.sub_agent_factory import SubAgentFactory

ADMIN = RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS["admin"]
POLICY = DelegationPolicy()


def test_a_child_at_the_depth_limit_gets_no_spawn_or_host_tools():
    """Red on base: the child collection was the full admin one, install_tool included."""
    names = set(child_tool_names(ADMIN, (), POLICY, child_depth=1))
    assert names
    assert not names & (SPAWN_TOOLS | {"install_tool", "ask_human", "schedule"})


def test_below_the_limit_a_child_may_still_delegate():
    deeper = DelegationPolicy(max_depth=2)
    names = set(child_tool_names(ADMIN, (), deeper, child_depth=1))
    assert "dispatch_parallel_tasks" in names and "install_tool" not in names
    assert "dispatch_parallel_tasks" not in child_tool_names(ADMIN, (), deeper, child_depth=2)


def test_role_and_requested_tools_narrow_the_set():
    researcher = RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS["researcher"]
    assert "bash" not in child_tool_names(researcher, (), POLICY, 1)
    # A request can only narrow a role, never add to it.
    assert child_tool_names(researcher, ["web_search", "bash"], POLICY, 1) == ["web_search"]


def test_policy_reads_settings_and_rejects_out_of_range():
    p = DelegationPolicy.from_mapping({"WEEBOT_DELEGATION_MAX_DEPTH": "2", "OTHER": "x"})
    assert p.max_depth == 2 and p.max_concurrent_children == 4
    with pytest.raises(ValueError):
        DelegationPolicy.from_mapping({"WEEBOT_DELEGATION_MAX_DEPTH": "9"})


@pytest.mark.asyncio
async def test_a_grandchild_is_denied_by_name():
    guard = DelegationGuard(POLICY)
    async with guard.enter("root") as depth:
        assert depth == 1 and current_depth() == 1
        with pytest.raises(DelegationDenied, match="max_depth=1"):
            async with guard.enter("child"):
                pass
    assert current_depth() == 0


@pytest.mark.asyncio
async def test_ten_spawns_never_exceed_the_bulkhead():
    guard = DelegationGuard(DelegationPolicy(max_concurrent_children=4))
    running = peak = 0

    async def child():
        nonlocal running, peak
        async with guard.enter("root"):
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

    await asyncio.gather(*[child() for _ in range(10)])
    assert peak == 4


@pytest.mark.asyncio
async def test_the_per_session_count_is_enforced():
    guard = DelegationGuard(DelegationPolicy(max_children_per_session=2))
    for _ in range(2):
        async with guard.enter("s"):
            pass
    with pytest.raises(DelegationDenied, match="max_children_per_session"):
        async with guard.enter("s"):
            pass
    async with guard.enter("other"):  # another session is unaffected
        pass


class _Flow:
    def __init__(self, events, delay=0.0):
        self._events, self._delay = events, delay

    async def run(self, prompt):
        for event in self._events:
            await asyncio.sleep(self._delay)
            yield event


@pytest.mark.asyncio
async def test_a_slow_child_is_cut_off_at_the_timeout():
    guard = DelegationGuard(DelegationPolicy(child_timeout_s=10))
    object.__setattr__(guard.policy, "child_timeout_s", 0)  # frozen model: shrink for the test
    flow = guard.wrap(_Flow(["x"], delay=0.2), "root")
    with pytest.raises(TimeoutError, match="child_timeout_s"):
        async for _ in flow.run("go"):
            pass
    assert current_depth() == 0


@pytest.mark.asyncio
async def test_a_wrapped_flow_passes_events_through():
    guard = DelegationGuard(POLICY)
    flow = guard.wrap(_Flow(["a", "b"]), "root")
    assert [e async for e in flow.run("go")] == ["a", "b"]


def _factory(guard, seen):
    def build(session, spec, llm, tools):
        seen.append(tools)
        return _Flow([MessageEvent(role="assistant", message="done")])

    return SubAgentFactory(
        llm=None,
        tools=None,
        cost_tracker=SimpleNamespace(record_cost=lambda *a: None),
        flow_factory=build,
        tools_for=lambda spec: f"tools:{spec.role.value}",
        guard=guard,
    )


@pytest.mark.asyncio
async def test_the_factory_scopes_tools_by_role_and_runs_inside_the_guard():
    seen = []
    factory = _factory(DelegationGuard(POLICY), seen)
    result = await factory.spawn(
        SubAgentSpec(role=SubAgentRole.REVIEWER, description="d", prompt="p")
    )
    assert result.status is SubAgentStatus.COMPLETED and seen == ["tools:reviewer"]


@pytest.mark.asyncio
async def test_the_factory_reports_a_denied_spawn_as_failed():
    guard = DelegationGuard(POLICY)
    factory = _factory(guard, [])
    spec = SubAgentSpec(description="d", prompt="p")
    async with guard.enter("root"):  # we are already a child: no further spawns
        result = await factory.spawn(spec)
    assert result.status is SubAgentStatus.FAILED and "max_depth" in result.error
