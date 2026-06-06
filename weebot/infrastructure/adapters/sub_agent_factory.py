"""SubAgentFactory — concrete adapter for spawning sub-agents.

Wraps DispatchAgentsTool for parallel dispatch and creates ephemeral
PlanActFlow instances.  Each sub-agent gets its own Session, runs
independently, and returns a structured SubAgentResult.
"""
from __future__ import annotations

import asyncio
import time
import logging
from typing import Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.sub_agent_cost_tracker_port import SubAgentCostTrackerPort
from weebot.application.ports.sub_agent_factory_port import SubAgentFactoryPort
from weebot.application.ports.swarm_event_bus_port import SwarmEventBusPort
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.session import Session, SessionStatus
from weebot.domain.models.sub_agent import (
    AgentTier,
    DispatchStrategy,
    SubAgentResult,
    SubAgentSpec,
    SubAgentStatus,
)
from weebot.domain.models.event import MessageEvent, ErrorEvent

logger = logging.getLogger(__name__)

# Default models per tier when spec.model is not set
_TIER_MODEL: dict[AgentTier, str] = {
    AgentTier.BUDGET: "minimax/minimax-m3",
    AgentTier.STANDARD: "qwen/qwen3.7-max",
    AgentTier.PREMIUM: "deepseek/deepseek-v4-pro",
}


class SubAgentFactory(SubAgentFactoryPort):
    """Spawns sub-agents as PlanActFlow instances in ephemeral sessions."""

    def __init__(
        self,
        llm: LLMPort,
        tools: ToolCollection,
        cost_tracker: SubAgentCostTrackerPort,
        swarm_bus: Optional[SwarmEventBusPort] = None,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._cost_tracker = cost_tracker
        self._swarm_bus = swarm_bus

    async def spawn(self, spec: SubAgentSpec) -> SubAgentResult:
        session = Session(
            id=f"sub-{spec.id}-{spec.role.value}",
            user_id="hyper_agent",
            agent_id=spec.role.value,
            status=SessionStatus.RUNNING,
        )
        # Build PlanActFlow inline to avoid circular imports at module level
        flow = self._build_flow(session, spec)
        start = time.monotonic()

        try:
            summary_parts: list[str] = []
            token_count = 0
            # If fresh mind, suppress the main agent's facts
            prompt = spec.prompt
            if spec.strategy == DispatchStrategy.FRESH_MIND:
                prompt = f"[FRESH CONTEXT — no prior session history]\n\n{spec.prompt}"

            gen = flow.run(prompt)
            while True:
                try:
                    event = await asyncio.wait_for(gen.__anext__(), timeout=spec.timeout_seconds)
                except StopAsyncIteration:
                    break
                if isinstance(event, MessageEvent) and event.role == "assistant":
                    summary_parts.append(event.message)
                if isinstance(event, ErrorEvent):
                    elapsed = time.monotonic() - start
                    return SubAgentResult(
                        spec_id=spec.id, agent_id=session.id,
                        role=spec.role.value,
                        status=SubAgentStatus.FAILED, error=event.error,
                        model_used=spec.model or _TIER_MODEL[spec.tier],
                        elapsed_seconds=elapsed,
                    )
                # Accumulate token usage from the flow
                if hasattr(flow, "token_usage"):
                    tu = flow.token_usage
                    token_count = max(token_count, tu.get("total_tokens", 0))

            elapsed = time.monotonic() - start
            summary = summary_parts[-1] if summary_parts else "(no output)"
            self._cost_tracker.record_cost(session.id, token_count, 0.0)

            return SubAgentResult(
                spec_id=spec.id, agent_id=session.id,
                role=spec.role.value,
                status=SubAgentStatus.COMPLETED,
                summary=summary,
                model_used=spec.model or _TIER_MODEL[spec.tier],
                tool_calls=0, tokens_used=token_count,
                elapsed_seconds=elapsed,
            )
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            return SubAgentResult(
                spec_id=spec.id, agent_id=session.id,
                role=spec.role.value,
                status=SubAgentStatus.TIMED_OUT,
                error=f"Timed out after {spec.timeout_seconds}s",
                model_used=spec.model or _TIER_MODEL[spec.tier],
                elapsed_seconds=elapsed,
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            return SubAgentResult(
                spec_id=spec.id, agent_id=session.id,
                role=spec.role.value,
                status=SubAgentStatus.FAILED,
                error=str(exc),
                model_used=spec.model or _TIER_MODEL[spec.tier],
                elapsed_seconds=elapsed,
            )

    async def spawn_parallel(
        self, specs: list[SubAgentSpec], max_concurrency: int = 4
    ) -> list[SubAgentResult]:
        sem = asyncio.Semaphore(max_concurrency)

        async def _run_one(s: SubAgentSpec) -> SubAgentResult:
            async with sem:
                return await self.spawn(s)

        return list(await asyncio.gather(*[_run_one(s) for s in specs]))

    async def spawn_multi_model(
        self, spec: SubAgentSpec, models: list[str] | None = None
    ) -> SubAgentResult:
        """Run the same spec on multiple models and return the best result.

        Uses longest-summary heuristic — not true voting. Future: implement
        majority-vote consensus when eval data shows improvement.
        """
        models = models or [
            "minimax/minimax-m3",
            "qwen/qwen3.7-max",
            "deepseek/deepseek-v4-pro",
        ]
        specs = [spec.with_model(m) for m in models[:3]]
        results = await self.spawn_parallel(specs, max_concurrency=3)
        successes = [r for r in results if r.is_success]
        if not successes:
            return results[0]
        return max(successes, key=lambda r: len(r.summary))

    def _build_flow(self, session: Session, spec: SubAgentSpec):
        """Build a PlanActFlow for a sub-agent session."""
        from weebot.application.flows.plan_act_flow import PlanActFlow
        from weebot.application.di import Container

        container = Container()
        container.configure_defaults()
        mediator = container.build_mediator()

        return PlanActFlow(
            llm=self._llm,
            tools=self._tools,
            session=session,
            event_bus=None,
            model=spec.model or _TIER_MODEL[spec.tier],
            mediator=mediator,
            state_repo=container._maybe_get("state_repo_port"),
            skill_prompt=None,
            max_steps=spec.max_tool_calls,
        )
