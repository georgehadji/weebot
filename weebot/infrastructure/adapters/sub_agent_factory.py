"""SubAgentFactory — concrete adapter for spawning sub-agents.

Wraps DispatchAgentsTool for parallel dispatch and creates ephemeral
PlanActFlow instances.  Each sub-agent gets its own Session, runs
independently, and returns a structured SubAgentResult.
"""

from __future__ import annotations

import asyncio
import time
import logging

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.sub_agent_cost_tracker_port import SubAgentCostTrackerPort
from weebot.application.ports.sub_agent_factory_port import SubAgentFactoryPort
from weebot.application.ports.swarm_event_bus_port import SwarmEventBusPort
from weebot.domain.models.session import Session, SessionStatus
from typing import Any


def _get_tool_collection_cls():
    import importlib as _il

    return _il.import_module("weebot.application.models.tool_collection").ToolCollection


from weebot.domain.models.sub_agent import (
    DispatchStrategy,
    SubAgentResult,
    SubAgentSpec,
    SubAgentStatus,
)
from weebot.domain.models.event import MessageEvent, ErrorEvent

logger = logging.getLogger(__name__)

from weebot.config.model_refs import SUBAGENT_TIER_MODEL

# Default models per tier when spec.model is not set
_TIER_MODEL = SUBAGENT_TIER_MODEL


class SubAgentFactory(SubAgentFactoryPort):
    """Spawns sub-agents as PlanActFlow instances in ephemeral sessions."""

    def __init__(
        self,
        llm: LLMPort,
        tools: Any,  # ToolCollection — resolved via _get_tool_collection_cls()
        cost_tracker: SubAgentCostTrackerPort,
        swarm_bus: SwarmEventBusPort | None = None,
        flow_factory: callable | None = None,
        cost_meter: Any | None = None,  # SessionCostMeter: rolls a child's spend up to its parent
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._cost_tracker = cost_tracker
        self._swarm_bus = swarm_bus
        self._flow_factory = flow_factory
        self._cost_meter = cost_meter

    async def spawn(self, spec: SubAgentSpec) -> SubAgentResult:
        session = Session(
            id=f"sub-{spec.id}-{spec.role.value}",
            user_id="hyper_agent",
            agent_id=spec.role.value,
            status=SessionStatus.RUNNING,
        )
        if self._cost_meter is not None:
            # The calling step's session is the parent. Without this link the child's
            # calls were totalled under its own id and the parent's limits never saw them.
            from weebot.core.log_context import session_id_var

            self._cost_meter.link(session.id, session_id_var.get() or "")
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
                        spec_id=spec.id,
                        agent_id=session.id,
                        role=spec.role.value,
                        status=SubAgentStatus.FAILED,
                        error=event.error,
                        model_used=spec.model or _TIER_MODEL[spec.tier],
                        elapsed_seconds=elapsed,
                    )
                # Accumulate token usage from the flow
                if hasattr(flow, "token_usage"):
                    tu = flow.token_usage
                    token_count = max(token_count, tu.get("total_tokens", 0))

            elapsed = time.monotonic() - start
            summary = summary_parts[-1] if summary_parts else "(no output)"
            spent = self._cost_meter.spent(session.id) if self._cost_meter is not None else 0.0
            self._cost_tracker.record_cost(session.id, token_count, spent)

            return SubAgentResult(
                spec_id=spec.id,
                agent_id=session.id,
                role=spec.role.value,
                status=SubAgentStatus.COMPLETED,
                summary=summary,
                model_used=spec.model or _TIER_MODEL[spec.tier],
                tool_calls=0,
                tokens_used=token_count,
                elapsed_seconds=elapsed,
            )
        except TimeoutError:
            elapsed = time.monotonic() - start
            return SubAgentResult(
                spec_id=spec.id,
                agent_id=session.id,
                role=spec.role.value,
                status=SubAgentStatus.TIMED_OUT,
                error=f"Timed out after {spec.timeout_seconds}s",
                model_used=spec.model or _TIER_MODEL[spec.tier],
                elapsed_seconds=elapsed,
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            return SubAgentResult(
                spec_id=spec.id,
                agent_id=session.id,
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
        models = models or list(SUBAGENT_TIER_MODEL.values())
        specs = [spec.with_model(m) for m in models[:3]]
        results = await self.spawn_parallel(specs, max_concurrency=3)
        successes = [r for r in results if r.is_success]
        if not successes:
            return results[0]
        return max(successes, key=lambda r: len(r.summary))

    def _build_flow(self, session: Session, spec: SubAgentSpec):
        """Build a PlanActFlow for a sub-agent session."""
        if self._flow_factory is None:
            raise RuntimeError(
                "SubAgentFactory requires a flow_factory. " "Inject via __init__(flow_factory=...)."
            )
        return self._flow_factory(session, spec, self._llm, self._tools)
