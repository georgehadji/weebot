"""Unit tests for DispatchAgentsTool.

The flow_factory is mocked — no real LLM or PlanActFlow is used. Tests verify:
- Parallel execution completes and collects results
- Semaphore respects max_concurrency
- Error handling (failed sub-agents, missing factory, empty tasks)
- ToolResult.data structure
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from weebot.tools.dispatch_agents import DispatchAgentsTool
from weebot.tools.base import ToolResult
from weebot.domain.models.event import AgentEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message_event(content: str) -> MagicMock:
    ev = MagicMock()
    ev.type = "MESSAGE"
    ev.content = content
    return ev


async def _flow_that_succeeds(prompt: str, summary: str = "done"):
    """Async generator yielding a final MessageEvent."""
    yield _make_message_event(summary)


def _factory_succeeds(summary: str = "done"):
    """Flow factory that always succeeds with a fixed summary."""
    def factory(session):
        flow = MagicMock()
        flow.run = AsyncMock(return_value=_flow_that_succeeds(session.id, summary))
        # Make run() return an async generator that yields one event
        async def _run(prompt):
            yield _make_message_event(summary)
        flow.run = _run
        return flow
    return factory


def _factory_raises():
    """Flow factory whose flows always raise an exception."""
    def factory(session):
        flow = MagicMock()
        async def _run(prompt):
            raise RuntimeError("sub-agent exploded")
            yield  # make it a generator
        flow.run = _run
        return flow
    return factory


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

class TestDispatchAgentsMetadata:
    def test_tool_name(self):
        assert DispatchAgentsTool().name == "dispatch_parallel_tasks"

    def test_description_mentions_parallel(self):
        assert "parallel" in DispatchAgentsTool().description.lower()

    def test_parameters_have_tasks_array(self):
        params = DispatchAgentsTool().parameters
        assert params["properties"]["tasks"]["type"] == "array"
        assert "tasks" in params["required"]

    def test_max_concurrency_has_default(self):
        params = DispatchAgentsTool().parameters
        assert params["properties"]["max_concurrency"]["default"] == 4


# ---------------------------------------------------------------------------
# No factory guard
# ---------------------------------------------------------------------------

class TestNoFactory:
    @pytest.mark.asyncio
    async def test_returns_error_without_factory(self):
        tool = DispatchAgentsTool()  # no flow_factory injected
        result = await tool.execute(tasks=[{"task_id": "t1", "description": "do something"}])
        assert result.is_error
        assert "flow_factory" in result.error

    @pytest.mark.asyncio
    async def test_returns_error_for_empty_tasks(self):
        tool = DispatchAgentsTool(flow_factory=_factory_succeeds())
        result = await tool.execute(tasks=[])
        assert result.is_error


# ---------------------------------------------------------------------------
# Successful parallel execution
# ---------------------------------------------------------------------------

class TestSuccessfulExecution:
    @pytest.mark.asyncio
    async def test_single_task_completes(self):
        tool = DispatchAgentsTool(flow_factory=_factory_succeeds("built hero"))
        result = await tool.execute(
            tasks=[{"task_id": "hero", "description": "Build the hero section"}]
        )
        assert result.success
        assert result.data["completed"] == 1
        assert result.data["failed"] == 0
        assert result.data["results"][0]["task_id"] == "hero"
        assert result.data["results"][0]["status"] == "completed"
        assert result.data["results"][0]["summary"] == "built hero"

    @pytest.mark.asyncio
    async def test_multiple_tasks_all_complete(self):
        tool = DispatchAgentsTool(flow_factory=_factory_succeeds("ok"))
        tasks = [
            {"task_id": f"section-{i}", "description": f"Build section {i}"}
            for i in range(4)
        ]
        result = await tool.execute(tasks=tasks, max_concurrency=4)
        assert result.success
        assert result.data["completed"] == 4
        assert result.data["failed"] == 0

    @pytest.mark.asyncio
    async def test_summary_output_contains_counts(self):
        tool = DispatchAgentsTool(flow_factory=_factory_succeeds())
        result = await tool.execute(
            tasks=[
                {"task_id": "a", "description": "task a"},
                {"task_id": "b", "description": "task b"},
            ]
        )
        assert "2 sub-agents" in result.output
        assert "2 completed" in result.output

    @pytest.mark.asyncio
    async def test_context_is_prepended_to_description(self):
        """Verify context is included in the prompt passed to the sub-agent."""
        received_prompts: list[str] = []

        def capturing_factory(session):
            flow = MagicMock()
            async def _run(prompt):
                received_prompts.append(prompt)
                yield _make_message_event("ok")
            flow.run = _run
            return flow

        tool = DispatchAgentsTool(flow_factory=capturing_factory)
        await tool.execute(tasks=[{
            "task_id": "t1",
            "description": "Build hero component",
            "context": "Spec: tasks/specs/hero.md",
        }])

        assert len(received_prompts) == 1
        assert "Spec: tasks/specs/hero.md" in received_prompts[0]
        assert "Build hero component" in received_prompts[0]


# ---------------------------------------------------------------------------
# Partial failures
# ---------------------------------------------------------------------------

class TestPartialFailures:
    @pytest.mark.asyncio
    async def test_failed_subtask_still_returns_success(self):
        """Tool itself succeeds even if a sub-agent raises."""
        tool = DispatchAgentsTool(flow_factory=_factory_raises())
        result = await tool.execute(
            tasks=[{"task_id": "bad-task", "description": "this will fail"}]
        )
        assert result.success  # Tool-level success (collection completed)
        assert result.data["failed"] == 1
        assert result.data["completed"] == 0
        assert "failed" in result.output.lower()

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self):
        call_count = 0

        def mixed_factory(session):
            nonlocal call_count
            call_count += 1
            idx = call_count

            flow = MagicMock()
            async def _run(prompt):
                if idx % 2 == 0:
                    raise RuntimeError("even tasks fail")
                yield _make_message_event("success")
            flow.run = _run
            return flow

        tool = DispatchAgentsTool(flow_factory=mixed_factory)
        tasks = [{"task_id": f"t{i}", "description": f"task {i}"} for i in range(4)]
        result = await tool.execute(tasks=tasks)

        assert result.success
        assert result.data["completed"] + result.data["failed"] == 4


# ---------------------------------------------------------------------------
# Concurrency limit
# ---------------------------------------------------------------------------

class TestConcurrencyLimit:
    @pytest.mark.asyncio
    async def test_max_concurrency_respected(self):
        """Verify semaphore prevents more than max_concurrency tasks at once."""
        active_count = 0
        max_seen = 0

        def counting_factory(session):
            flow = MagicMock()
            async def _run(prompt):
                nonlocal active_count, max_seen
                active_count += 1
                max_seen = max(max_seen, active_count)
                await asyncio.sleep(0.01)  # brief delay to allow overlap
                active_count -= 1
                yield _make_message_event("done")
            flow.run = _run
            return flow

        tool = DispatchAgentsTool(flow_factory=counting_factory)
        tasks = [{"task_id": f"t{i}", "description": f"task {i}"} for i in range(8)]
        await tool.execute(tasks=tasks, max_concurrency=3)

        assert max_seen <= 3, f"max_seen={max_seen} exceeded max_concurrency=3"


# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------

class TestSessionCreation:
    @pytest.mark.asyncio
    async def test_each_task_gets_unique_session_id(self):
        session_ids: list[str] = []

        def capturing_factory(session):
            session_ids.append(session.id)
            flow = MagicMock()
            async def _run(prompt):
                yield _make_message_event("ok")
            flow.run = _run
            return flow

        tool = DispatchAgentsTool(flow_factory=capturing_factory)
        await tool.execute(tasks=[
            {"task_id": "t1", "description": "a"},
            {"task_id": "t2", "description": "b"},
        ])

        assert len(session_ids) == 2
        assert session_ids[0] != session_ids[1]
        assert "dispatch-t1" in session_ids[0]
        assert "dispatch-t2" in session_ids[1]
