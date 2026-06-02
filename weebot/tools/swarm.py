"""SwarmTool — goal-driven parallel agent orchestration (Phase 1).

Usage from an agent:
    swarm(prompt="Research the competitive landscape for AI coding tools")

What happens:
    1. GoalAgent decomposes the prompt into a SwarmSpec (3-8 sub-goals
       with auto-generated roles and tool assignments).
    2. Each sub-goal runs as an independent PlanActFlow sub-agent via
       dispatch_parallel_tasks.
    3. SynthesizerAgent clusters results, identifies consensus/dissent,
       and produces a structured synthesis report.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from weebot.tools.base import BaseTool, ToolResult
from weebot.domain.models.swarm import SwarmSpec

logger = logging.getLogger(__name__)


class SwarmTool(BaseTool):
    """Decompose a complex task into sub-goals, spawn parallel agents,
    and synthesize results — all driven by a single prompt."""

    name: str = "swarm"
    description: str = (
        "Decompose a complex research or analysis task into parallel sub-goals, "
        "spawn independent agents for each sub-goal with auto-generated roles, "
        "and synthesize all findings into one structured report. "
        "Best for: competitive analysis, market research, open-ended exploration "
        "where you don't know in advance what sub-tasks are needed. "
        "NOT for: simple lookups, single-fact questions, or tasks with "
        "strong sequential dependencies."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The research question or analysis task to decompose.",
            },
            "max_goals": {
                "type": "integer",
                "description": "Maximum number of sub-goals to create (default: 6, max: 8).",
                "default": 6,
            },
            "max_concurrency": {
                "type": "integer",
                "description": "How many sub-agents run at the same time (default: 4).",
                "default": 4,
            },
        },
        "required": ["prompt"],
    }

    # Injected dependencies
    _llm: Any = None
    _flow_factory: Any = None

    def __init__(
        self,
        llm: Any = None,
        flow_factory: Any = None,
        **data: Any,
    ) -> None:
        super().__init__(**data)
        object.__setattr__(self, "_llm", llm)
        object.__setattr__(self, "_flow_factory", flow_factory)

    async def execute(
        self,
        prompt: str,
        max_goals: int = 6,
        max_concurrency: int = 4,
        **_: Any,
    ) -> ToolResult:
        if not self._llm:
            return ToolResult.error_result(
                "SwarmTool has no LLMPort — wire it via DI"
            )

        max_goals = min(max(max_goals, 1), 8)
        t_start = time.monotonic()

        # 1. Decompose
        from weebot.application.agents.goal_agent import GoalAgent

        goal_agent = GoalAgent(self._llm)
        try:
            spec: SwarmSpec = await goal_agent.decompose(
                prompt, max_goals=max_goals
            )
        except Exception as exc:
            return ToolResult.error_result(f"Goal decomposition failed: {exc}")

        if not spec.goals:
            return ToolResult.error_result("GoalAgent produced no sub-goals")

        logger.info(
            "Swarm: %d goals, concurrency=%d, strategy=%s",
            len(spec.goals), spec.max_concurrency, spec.synthesis_strategy,
        )

        # 2. Create swarm event bus and dispatch
        from weebot.infrastructure.swarm_event_bus import SwarmEventBus
        swarm_bus = SwarmEventBus()
        tasks = []
        for goal in spec.goals:
            tasks.append({
                "task_id": goal.id,
                "description": (
                    f"Goal: {goal.description}\n"
                    f"Role: {goal.role}\n"
                    f"Use tools: {', '.join(goal.tools)}"
                ),
            })

        from weebot.tools.dispatch_agents import DispatchAgentsTool

        dispatcher = DispatchAgentsTool(
            flow_factory=self._flow_factory,
            swarm_bus=swarm_bus,
        )
        dispatch_result = await dispatcher.execute(
            tasks=tasks,
            max_concurrency=min(max_concurrency, spec.max_concurrency),
        )

        # 3. Synthesize — optionally using swarm bus for real-time insights
        sub_results = dispatch_result.data.get("results", [])
        from weebot.application.agents.synthesizer_agent import SynthesizerAgent

        # Collect bus messages for richer context
        insight_history = swarm_bus.get_all_topics()
        bus_insights = {}
        for topic in insight_history:
            msgs = swarm_bus.get_history(topic)
            bus_insights[topic] = [m.payload for m in msgs]

        synthesizer = SynthesizerAgent(self._llm)
        swarm_result = await synthesizer.synthesize(
            prompt=prompt,
            results=sub_results,
            strategy=spec.synthesis_strategy,
        )

        swarm_result.elapsed_seconds = time.monotonic() - t_start

        # Format output
        completed = dispatch_result.data.get("completed", 0)
        failed = dispatch_result.data.get("failed", 0)
        header = (
            f"## Swarm Results\n"
            f"**Prompt:** {prompt[:200]}\n"
            f"**Agents:** {completed} completed, {failed} failed "
            f"({swarm_result.elapsed_seconds:.1f}s)\n\n"
        )

        return ToolResult.success_result(
            output=header + swarm_result.synthesis,
            data={
                "swarm_result": swarm_result.model_dump(),
                "sub_results": sub_results,
                "completed": completed,
                "failed": failed,
                "elapsed_seconds": swarm_result.elapsed_seconds,
            },
        )
