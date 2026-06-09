"""ParallelAgentRouter — route tasks to parallel sub-agents for complex work.

Extends TaskRouterPort with the ability to decompose a task and farm
sub-tasks to parallel sub-agents.  For simple tasks, falls back to
keyword-based routing (preserving existing behavior).

Design:
- For tasks classified as complex/high complexity, spawns N independent
  sub-agents via SubAgentFactoryPort and returns a TaskRoute with
  parallel_subtasks populated.
- For simple/standard tasks, delegates to the fallback KeywordTaskRouter.
- Never blocks: if sub-agent creation fails, falls back to single-agent.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, TYPE_CHECKING

from weebot.application.ports.task_router_port import TaskRouterPort
from weebot.application.services.keyword_task_router import KeywordTaskRouter
from weebot.domain.models.task_route import TaskCategory, TaskComplexity, TaskRoute

if TYPE_CHECKING:
    from weebot.application.ports.sub_agent_factory_port import SubAgentFactoryPort

logger = logging.getLogger(__name__)


class ParallelAgentRouter(TaskRouterPort):
    """Tasks are routed to parallel sub-agents when the complexity warrants it.

    Args:
        fallback: Optional fallback router (default: KeywordTaskRouter).
        sub_agent_factory: Optional SubAgentFactoryPort for spawning sub-agents.
        max_parallel: Maximum parallel sub-agents to spawn (default 3).
    """

    def __init__(
        self,
        fallback: Optional[TaskRouterPort] = None,
        sub_agent_factory: Optional["SubAgentFactoryPort"] = None,
        max_parallel: int = 3,
    ) -> None:
        self._fallback = fallback or KeywordTaskRouter()
        self._sub_factory = sub_agent_factory
        self._max_parallel = max_parallel

    async def route(self, query: str) -> TaskRoute:
        """Classify *query* and return a TaskRoute.

        For high-complexity tasks with a sub-agent factory available,
        spawns parallel sub-agents and returns their results.
        """
        base = await self._fallback.route(query)

        if base.complexity == TaskComplexity.HIGH and self._sub_factory is not None:
            try:
                subtasks = await self._decompose_and_farm(query, base)
                if subtasks:
                    return TaskRoute(
                        category=base.category,
                        complexity=base.complexity,
                        flow_type=base.flow_type,
                        tool_restriction=base.tool_restriction,
                        confidence=base.confidence,
                        parallel_subtasks=subtasks,
                    )
            except Exception as exc:
                logger.warning(
                    "Parallel routing failed for %r — falling back to single-agent: %s",
                    query[:80], exc,
                )

        return base

    async def refresh(self) -> None:
        """Reload classification config."""
        await self._fallback.refresh()

    async def _decompose_and_farm(
        self, query: str, base: TaskRoute,
    ) -> list[dict]:
        """Decompose *query* into parallel sub-tasks and farm them out.

        Returns a list of subtask descriptors, or [] on failure.
        """
        if self._sub_factory is None:
            return []

        from weebot.domain.models.sub_agent import (
            SubAgentSpec,
            SubAgentRole,
            AgentTier,
            DispatchStrategy,
        )

        sub_count = min(self._max_parallel, 3)

        specs = [
            SubAgentSpec(
                role=SubAgentRole.RESEARCHER,
                description=f"Sub-task {i+1}/{sub_count} for: {query[:100]}",
                prompt=f"{query} — part {i+1}/{sub_count}",
                tier=AgentTier.BUDGET,
                strategy=DispatchStrategy.PARALLEL,
                max_tool_calls=10,
            )
            for i in range(sub_count)
        ]

        results = await self._sub_factory.spawn_parallel(specs, max_concurrency=sub_count)

        subtask_list: list[dict] = []
        for i, result in enumerate(results):
            if result.status.value in ("failed", "timed_out"):
                logger.warning("Sub-task %d %s: %s", i, result.status.value, result.error or "")
                continue
            subtask_list.append({
                "index": i,
                "description": f"{query} — part {i+1}/{sub_count}",
                "summary": result.summary,
                "model_used": result.model_used,
                "tool_calls": result.tool_calls,
            })

        return subtask_list
