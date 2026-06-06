"""HyperAgent — top-level orchestrator for multi-agent workflows.

Decomposes tasks into SubAgentSpecs via GoalAgent, dispatches via
SubAgentFactoryPort, cost-gates per tier, and synthesizes via
SynthesizerAgent.

Implements the Tool→Skill→Subagent decision gate from Will's workshop.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from weebot.application.agents.goal_agent import GoalAgent
from weebot.application.agents.synthesizer_agent import SynthesizerAgent
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.sub_agent_cost_tracker_port import SubAgentCostTrackerPort
from weebot.application.ports.sub_agent_factory_port import SubAgentFactoryPort
from weebot.application.ports.swarm_event_bus_port import SwarmEventBusPort
from weebot.domain.models.agent_capability import AGENT_CAPABILITIES, AgentCapability
from weebot.domain.models.sub_agent import (
    AgentTier,
    DispatchStrategy,
    SubAgentResult,
    SubAgentRole,
    SubAgentSpec,
)
from weebot.domain.models.swarm import SwarmResult, SwarmSpec

logger = logging.getLogger(__name__)


class HyperAgent:
    """Top-level orchestrator. One instance per user task.

    Lifecycle: classify → decompose → cost-gate → dispatch → synthesize
    """

    def __init__(
        self,
        llm: LLMPort,
        event_bus: EventBusPort,
        swarm_bus: SwarmEventBusPort,
        sub_agent_factory: SubAgentFactoryPort,
        cost_tracker: SubAgentCostTrackerPort,
        model: Optional[str] = None,
        max_concurrency: int = 4,
    ) -> None:
        self._llm = llm
        self._event_bus = event_bus
        self._swarm_bus = swarm_bus
        self._factory = sub_agent_factory
        self._cost_tracker = cost_tracker
        self._model = model
        self._max_concurrency = max_concurrency

        self._goal_agent = GoalAgent(llm=llm)
        self._synthesizer = SynthesizerAgent(llm=llm)

    async def execute(self, prompt: str) -> SwarmResult:
        """Execute a task using the multi-agent workflow. Returns synthesized result."""
        strategy = self._classify_task(prompt)
        swarm_spec: SwarmSpec = await self._goal_agent.decompose(prompt)
        specs = self._specs_from_swarm(swarm_spec, strategy)
        specs = self._apply_cost_gating(specs)

        if not specs:
            raise RuntimeError("Budget exhausted — cannot dispatch any sub-agents")

        # Dispatch
        if strategy == DispatchStrategy.SEQUENTIAL:
            results = [await self._factory.spawn(s) for s in specs]
        elif strategy == DispatchStrategy.VOTED and len(specs) == 1:
            results = [await self._factory.spawn_multi_model(specs[0])]
        else:
            results = await self._factory.spawn_parallel(
                specs, max_concurrency=self._max_concurrency
            )

        return await self._synthesize(prompt, results, swarm_spec)

    # ── Decision Gate ─────────────────────────────────────────────

    @staticmethod
    def _classify_task(prompt: str) -> DispatchStrategy:
        """Heuristic v1 — regex-based. Replace with LLM classifier when eval data exists."""
        lo = prompt.lower()
        parallel_patterns = [
            r"in parallel", r"each\b.*separately", r"independently",
            r"\bfor each\b", r"simultaneously", r"all at once",
        ]
        if any(re.search(p, lo) for p in parallel_patterns):
            return DispatchStrategy.PARALLEL
        fresh_mind = ("review", "critique", "audit", "verify", "red team")
        if any(kw in lo for kw in fresh_mind):
            return DispatchStrategy.FRESH_MIND
        voting = ("security", "financial", "legal", "compliance", "safety")
        if any(kw in lo for kw in voting):
            return DispatchStrategy.VOTED
        return DispatchStrategy.PARALLEL

    # ── Spec generation ───────────────────────────────────────────

    def _specs_from_swarm(
        self, swarm: SwarmSpec, strategy: DispatchStrategy
    ) -> list[SubAgentSpec]:
        specs: list[SubAgentSpec] = []
        for goal in swarm.goals:
            role = self._map_role(goal.role)
            cap = AGENT_CAPABILITIES[role]
            effective = DispatchStrategy.FRESH_MIND if cap.requires_fresh_context else strategy
            specs.append(SubAgentSpec(
                role=role,
                description=goal.description,
                prompt=goal.description,
                tier=cap.tier,
                strategy=effective,
                tools=goal.tools or cap.default_tools,
                model=cap.preferred_models[0] if cap.preferred_models else None,
                max_tool_calls=cap.max_tool_calls,
            ))
        return specs

    @staticmethod
    def _map_role(role_name: str) -> SubAgentRole:
        try:
            return SubAgentRole(role_name.lower())
        except ValueError:
            return SubAgentRole.RESEARCHER

    # ── Cost gating ───────────────────────────────────────────────

    def _apply_cost_gating(self, specs: list[SubAgentSpec]) -> list[SubAgentSpec]:
        result: list[SubAgentSpec] = []
        for spec in specs:
            est = spec.max_tool_calls * 2000
            if self._cost_tracker.can_afford(spec.tier, est):
                result.append(spec)
            elif self._cost_tracker.can_afford(AgentTier.BUDGET, est):
                cap = AGENT_CAPABILITIES[spec.role]
                budget_model = next(
                    (m for m in cap.preferred_models if "free" in m or "minimax" in m),
                    cap.preferred_models[-1] if cap.preferred_models else None,
                )
                downgraded = spec.with_tier(AgentTier.BUDGET)
                if budget_model:
                    downgraded = downgraded.with_model(budget_model)
                result.append(downgraded)
            else:
                logger.warning("Budget exhausted — skipping: %s (%s)", spec.role.value, spec.id)
        return result

    # ── Synthesis ─────────────────────────────────────────────────

    async def _synthesize(
        self,
        original_prompt: str,
        results: list[SubAgentResult],
        swarm_spec: SwarmSpec,
    ) -> SwarmResult:
        """Call SynthesizerAgent with the actual signature it expects."""
        summaries = [
            {"role": r.role, "summary": r.summary, "model_used": r.model_used}
            for r in results if r.is_success
        ]
        if not summaries:
            raise RuntimeError("All sub-agents failed — nothing to synthesize")
        return await self._synthesizer.synthesize(
            prompt=original_prompt,
            results=summaries,
            strategy=swarm_spec.synthesis_strategy,
        )
