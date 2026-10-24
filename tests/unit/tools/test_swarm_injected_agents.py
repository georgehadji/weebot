"""SwarmTool runs on injected decompose/synthesize callables (plan 3.3)."""

from __future__ import annotations

import pytest

from weebot.domain.models.swarm import SubGoal, SwarmResult, SwarmSpec
from weebot.domain.models.tool_result import ToolResult
from weebot.tools.swarm import SwarmTool


class _Bus:
    def get_all_topics(self):
        return []


@pytest.mark.asyncio
async def test_injected_callables_drive_the_tool(monkeypatch):
    calls = {}

    async def decompose(prompt, max_goals):
        calls["decompose"] = (prompt, max_goals)
        return SwarmSpec(goals=[SubGoal(id="g1", description="d", role="r")])

    async def synthesize(prompt, results, strategy):
        calls["synthesize"] = (prompt, results, strategy)
        return SwarmResult(prompt=prompt, synthesis="done")

    class _Dispatcher:
        def __init__(self, **_):
            pass

        async def execute(self, **_):
            return ToolResult.success_result(
                output="", data={"results": [{"goal_id": "g1"}], "completed": 1, "failed": 0}
            )

    monkeypatch.setattr("weebot.tools.dispatch_agents.DispatchAgentsTool", _Dispatcher)
    tool = SwarmTool(llm=object(), swarm_bus=_Bus(), decompose=decompose, synthesize=synthesize)

    result = await tool.execute(prompt="p", max_goals=3)

    assert result.success
    assert calls["decompose"] == ("p", 3)
    assert calls["synthesize"] == ("p", [{"goal_id": "g1"}], "cluster")
    assert "done" in result.output


@pytest.mark.asyncio
async def test_decompose_failure_is_reported():
    async def decompose(prompt, max_goals):
        raise RuntimeError("boom")

    async def synthesize(prompt, results, strategy):  # never reached
        raise AssertionError("synthesize must not run after a failed decomposition")

    tool = SwarmTool(llm=object(), decompose=decompose, synthesize=synthesize)
    result = await tool.execute(prompt="p")
    assert not result.success
    assert "boom" in result.error


@pytest.mark.asyncio
async def test_an_unwired_tool_says_so_instead_of_importing_agents():
    result = await SwarmTool(llm=object()).execute(prompt="p")
    assert not result.success
    assert "wire it via the tool registry" in result.error
