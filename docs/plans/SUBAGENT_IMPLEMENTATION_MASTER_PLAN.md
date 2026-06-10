# Weebot Multi-Agent System — Implementation Plan

> **Architecture:** Hexagonal (Ports & Adapters) · **Pattern:** CQRS + State Machine · **Models:** Pydantic v2 frozen
> **Source:** Will's Anthropic Applied AI workshop "Tool, skill, or subagent?" + weebot forensic audit
> **Last verified against codebase:** 2026-06-06

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Domain Layer — New Models](#2-domain-layer--new-models)
3. [Application Layer — Ports](#3-application-layer--ports)
4. [Application Layer — Agents](#4-application-layer--agents)
5. [Application Layer — Flows](#5-application-layer--flows)
6. [Application Layer — CQRS](#6-application-layer--cqrs)
7. [Infrastructure Layer — Adapters](#7-infrastructure-layer--adapters)
8. [Tool Layer — Agent Tools](#8-tool-layer--agent-tools)
9. [DI Container — Wiring](#9-di-container--wiring)
10. [CLI — Entry Points](#10-cli--entry-points)
11. [System Prompts](#11-system-prompts)
12. [Testing Strategy](#12-testing-strategy)
13. [Migration & Rollout](#13-migration--rollout)
14. [Appendix A: Codebase Alignment Notes](#appendix-a-codebase-alignment-notes)
15. [Appendix B: Industry Best Practices](#appendix-b-industry-best-practices)
16. [Appendix C: File Manifest](#appendix-c-file-manifest)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      INTERFACES LAYER                           │
│  cli/commands/hyper.py    run.py --hyper    web/routers/hyper.py │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                     APPLICATION LAYER                            │
│                                                                  │
│  ┌─────────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ HyperAgentFlow  │  │ CQRS Commands│  │ Pipeline Behaviors│  │
│  │ (state machine) │  │ + Handlers   │  │ (log, telemetry,  │  │
│  │                 │  │              │  │  save-policy)     │  │
│  └────────┬────────┘  └──────┬───────┘  └────────┬──────────┘  │
│           │                  │                    │              │
│  ┌────────▼─────────────────────────────────────────────────┐   │
│  │                     AGENT LAYER                           │   │
│  │  HyperAgent   GoalAgent(*)   SynthesizerAgent(*)         │   │
│  └──────────────────────────┬────────────────────────────────┘   │
│                             │                                    │
│  ┌──────────────────────────▼────────────────────────────────┐   │
│  │                     PORTS (ABCs)                           │   │
│  │  SwarmEventBusPort(*)  SubAgentFactoryPort  CostTracker   │   │
│  └───────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                   INFRASTRUCTURE LAYER                           │
│  SwarmEventBus(*)   SubAgentFactory   SubAgentCostTracker       │
│  AdaptiveSemaphore                                              │
└─────────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                       DOMAIN LAYER                               │
│  SubAgentSpec  SubAgentResult  AgentCapability  WorkflowMemory  │
│  InterAgentMessage(*)  SwarmSpec(*)  SwarmResult(*)              │
│  (Pydantic v2, frozen, zero external dependencies)              │
└─────────────────────────────────────────────────────────────────┘

(*) = already exists — modify or extend, do not recreate
```

---

## 2. Domain Layer — New Models

All new models use Pydantic v2 `BaseModel` with `ConfigDict(frozen=True)` and `model_copy(update={...})` for state transitions. Zero imports from outer layers.

### 2.1 `SubAgentSpec` — `weebot/domain/models/sub_agent.py`

```python
"""Sub-agent specification and result domain models."""
from __future__ import annotations

from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class SubAgentRole(str, Enum):
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    CODER = "coder"
    DESIGNER = "designer"
    REVIEWER = "reviewer"
    AUTOMATION = "automation"
    PLANNER = "planner_sub"
    DOCUMENTER = "documentation"


class AgentTier(str, Enum):
    BUDGET = "budget"       # FREE models only, max 5 tool calls
    STANDARD = "standard"   # FREE → budget paid, max 15 tool calls
    PREMIUM = "premium"     # Best available, max 50 tool calls


class DispatchStrategy(str, Enum):
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"
    FRESH_MIND = "fresh_mind"
    VOTED = "voted"


class SubAgentSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    role: SubAgentRole = Field(default=SubAgentRole.RESEARCHER)
    description: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    tier: AgentTier = Field(default=AgentTier.STANDARD)
    strategy: DispatchStrategy = Field(default=DispatchStrategy.PARALLEL)
    tools: list[str] = Field(default_factory=list)
    model: Optional[str] = Field(default=None)
    max_tool_calls: int = Field(default=15, ge=1, le=50)
    timeout_seconds: int = Field(default=300, ge=30, le=1800)
    output_schema: Optional[dict] = Field(default=None)

    def with_model(self, model: str) -> SubAgentSpec:
        return self.model_copy(update={"model": model})

    def with_strategy(self, strategy: DispatchStrategy) -> SubAgentSpec:
        return self.model_copy(update={"strategy": strategy})

    def with_tier(self, tier: AgentTier) -> SubAgentSpec:
        return self.model_copy(update={"tier": tier})
```

**Changes from original plan:**
- Added `ConfigDict(frozen=True)` for real immutability.
- Removed `default=""` on `description` and `prompt` — they had `min_length=1` which contradicts an empty default. These are now required fields (no default).
- Added `with_tier()` helper for cost-gating downgrades.

### 2.2 `SubAgentResult` — same file, continued

```python
class SubAgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class SubAgentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    spec_id: str
    agent_id: str
    status: SubAgentStatus = Field(default=SubAgentStatus.PENDING)
    summary: str = Field(default="")
    data: dict = Field(default_factory=dict)
    error: Optional[str] = Field(default=None)
    model_used: str = Field(default="")
    tool_calls: int = Field(default=0)
    tokens_used: int = Field(default=0)
    cost_usd: float = Field(default=0.0)
    elapsed_seconds: float = Field(default=0.0)

    @property
    def is_success(self) -> bool:
        return self.status == SubAgentStatus.COMPLETED
```

**Changes from original plan:**
- Made `spec_id` and `agent_id` required (no empty default — these identify the result).
- Removed `findings: list[InterAgentMessage]` — findings live on the `SwarmEventBus`, not duplicated into results. This avoids a circular domain-model dependency and keeps results serialization-friendly.

### 2.3 `AgentCapability` — `weebot/domain/models/agent_capability.py`

```python
"""Agent capability profiles — static registry of what each role can do."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from weebot.domain.models.sub_agent import AgentTier, SubAgentRole


class AgentCapability(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: SubAgentRole
    tier: AgentTier = Field(default=AgentTier.STANDARD)
    default_tools: list[str] = Field(default_factory=list)
    preferred_models: list[str] = Field(default_factory=list)
    max_concurrency: int = Field(default=4, ge=1, le=8)
    max_tool_calls: int = Field(default=15, ge=1, le=50)
    requires_fresh_context: bool = Field(default=False)


AGENT_CAPABILITIES: dict[SubAgentRole, AgentCapability] = {
    SubAgentRole.RESEARCHER: AgentCapability(
        role=SubAgentRole.RESEARCHER,
        tier=AgentTier.STANDARD,
        default_tools=["web_search", "browser_inspector", "knowledge", "file_editor"],
        preferred_models=["minimax/minimax-m3", "qwen/qwen3.7-max"],
        max_concurrency=4,
        max_tool_calls=20,
    ),
    SubAgentRole.ANALYST: AgentCapability(
        role=SubAgentRole.ANALYST,
        tier=AgentTier.STANDARD,
        default_tools=["python_execute", "file_editor", "bash", "knowledge"],
        preferred_models=["qwen/qwen3.7-max", "minimax/minimax-m3"],
        max_concurrency=2,
        max_tool_calls=15,
    ),
    SubAgentRole.CODER: AgentCapability(
        role=SubAgentRole.CODER,
        tier=AgentTier.STANDARD,
        default_tools=["bash", "python_execute", "file_editor", "web_search"],
        preferred_models=["qwen/qwen3.7-max", "deepseek/deepseek-v4-pro"],
        max_concurrency=2,
        max_tool_calls=30,
    ),
    SubAgentRole.DESIGNER: AgentCapability(
        role=SubAgentRole.DESIGNER,
        tier=AgentTier.PREMIUM,
        default_tools=["image_gen", "file_editor", "browser_inspector"],
        preferred_models=["minimax/minimax-m3"],
        max_concurrency=3,
        max_tool_calls=20,
    ),
    SubAgentRole.REVIEWER: AgentCapability(
        role=SubAgentRole.REVIEWER,
        tier=AgentTier.BUDGET,
        default_tools=["file_editor", "web_search", "knowledge"],
        preferred_models=["minimax/minimax-m3"],
        max_concurrency=2,
        max_tool_calls=10,
        requires_fresh_context=True,
    ),
    SubAgentRole.AUTOMATION: AgentCapability(
        role=SubAgentRole.AUTOMATION,
        tier=AgentTier.STANDARD,
        default_tools=["bash", "computer_use", "file_editor", "python_execute"],
        preferred_models=["minimax/minimax-m3", "qwen/qwen3.7-max"],
        max_concurrency=2,
        max_tool_calls=25,
    ),
    SubAgentRole.PLANNER: AgentCapability(
        role=SubAgentRole.PLANNER,
        tier=AgentTier.BUDGET,
        default_tools=["file_editor", "knowledge", "web_search"],
        preferred_models=["minimax/minimax-m3"],
        max_concurrency=1,
        max_tool_calls=8,
    ),
    SubAgentRole.DOCUMENTER: AgentCapability(
        role=SubAgentRole.DOCUMENTER,
        tier=AgentTier.BUDGET,
        default_tools=["file_editor", "knowledge", "web_search"],
        preferred_models=["minimax/minimax-m3"],
        max_concurrency=2,
        max_tool_calls=12,
    ),
}
```

**Changes from original plan:**
- Removed `supports_voting` and `description` from the model — voting is a dispatch strategy (on `SubAgentSpec`), not a capability attribute. Descriptions are redundant with role names.
- Removed `"advanced_browser"` from DESIGNER tools — this tool exists only on the `admin` and `researcher` roles in the actual registry.
- Removed `"schedule"` from AUTOMATION tools — the `schedule` tool is only in `admin` role currently.

### 2.4 `WorkflowMemory` — `weebot/domain/models/workflow_memory.py`

```python
"""Workflow-scoped shared memory for multi-agent coordination."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class MemoryEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str = Field(min_length=1)
    value: Any = Field(default=None)
    source_agent_id: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkflowMemory(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str = Field(default_factory=lambda: str(uuid4()))
    entries: tuple[MemoryEntry, ...] = Field(default_factory=tuple)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add(self, key: str, value: Any, agent_id: str, confidence: float = 0.5) -> WorkflowMemory:
        entry = MemoryEntry(key=key, value=value, source_agent_id=agent_id, confidence=confidence)
        return self.model_copy(update={"entries": self.entries + (entry,)})

    def get(self, key: str) -> Optional[MemoryEntry]:
        for entry in reversed(self.entries):
            if entry.key == key:
                return entry
        return None

    def snapshot(self) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        for entry in self.entries:
            seen[entry.key] = entry.value
        return seen
```

**Changes from original plan:**
- Changed `entries` from `list` to `tuple` — a frozen model with a mutable list inside defeats the purpose of immutability.
- Made `source_agent_id` and `key` required (no empty defaults for identity fields).
- Removed `get_all()` — YAGNI. The `snapshot()` already covers the "latest value per key" use case.

---

## 3. Application Layer — Ports

### 3.1 `SubAgentFactoryPort` — `weebot/application/ports/sub_agent_factory_port.py`

```python
"""Port for sub-agent lifecycle management."""
from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.sub_agent import SubAgentResult, SubAgentSpec


class SubAgentFactoryPort(ABC):

    @abstractmethod
    async def spawn(self, spec: SubAgentSpec) -> SubAgentResult:
        """Spawn a single sub-agent and return its result."""
        ...

    @abstractmethod
    async def spawn_parallel(
        self, specs: list[SubAgentSpec], max_concurrency: int = 4
    ) -> list[SubAgentResult]:
        """Spawn multiple sub-agents with concurrency control."""
        ...

    @abstractmethod
    async def spawn_voted(
        self, spec: SubAgentSpec, models: list[str] | None = None
    ) -> SubAgentResult:
        """Run the same spec on 2-3 models and return the consensus result."""
        ...
```

**Changes from original plan:**
- `spawn()` now returns `SubAgentResult` directly instead of `AsyncGenerator[AgentEvent, None]`. The original plan had `spawn()` yield events AND a `SubAgentResult`, which violated the generator's type contract (`SubAgentResult` is not an `AgentEvent`). Progress events should go through the `EventBusPort` instead.

### 3.2 `SubAgentCostTrackerPort` — `weebot/application/ports/sub_agent_cost_tracker_port.py`

Unchanged from original plan — the interface is clean.

```python
"""Port for tracking sub-agent cost budgets."""
from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.sub_agent import AgentTier


class SubAgentCostTrackerPort(ABC):

    @abstractmethod
    def can_afford(self, tier: AgentTier, estimated_tokens: int) -> bool: ...

    @abstractmethod
    def record_cost(self, agent_id: str, tokens: int, cost_usd: float) -> None: ...

    @abstractmethod
    def remaining_budget(self) -> float: ...

    @abstractmethod
    def summary(self) -> dict: ...
```

### 3.3 `SwarmEventBusPort` — MODIFY existing `weebot/application/ports/swarm_event_bus_port.py`

The existing port is marked `[DEPRECATED]` and is missing methods that both the concrete `SwarmEventBus` and the plan's `HyperAgent` require. It also has a signature mismatch: the port defines `publish(topic, message)` but the concrete bus defines `publish(message)` where the topic comes from `message.topic`.

**Required changes:**
1. Remove the `[DEPRECATED]` marker.
2. Align `publish()` signature with the concrete adapter: `publish(message: InterAgentMessage)`.
3. Add `get_history()` and `get_all_topics()` — both already exist on the concrete `SwarmEventBus`.

```python
"""Swarm Event Bus port — inter-agent message routing."""
from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.inter_agent import InterAgentMessage


class SwarmEventBusPort(ABC):

    @abstractmethod
    async def publish(self, message: InterAgentMessage) -> None: ...

    @abstractmethod
    async def subscribe(self, topic: str, handler) -> None: ...

    @abstractmethod
    def get_history(self, topic: str) -> list[InterAgentMessage]: ...

    @abstractmethod
    def get_all_topics(self) -> list[str]: ...

    @abstractmethod
    async def close(self) -> None: ...
```

---

## 4. Application Layer — Agents

### 4.1 `HyperAgent` — `weebot/application/agents/hyper_agent.py`

```python
"""HyperAgent — top-level orchestrator for multi-agent workflows.

Decomposes tasks into SubAgentSpecs via GoalAgent, dispatches via
SubAgentFactoryPort, and synthesizes results via SynthesizerAgent.

Implements the Tool→Skill→Subagent decision gate.
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
from weebot.domain.models.agent_capability import AGENT_CAPABILITIES
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
        cost_limit_usd: float = 0.50,
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

        # 1. Classify dispatch strategy
        strategy = self._classify_task(prompt)

        # 2. Decompose into sub-goals
        swarm_spec: SwarmSpec = await self._goal_agent.decompose(prompt)
        specs = self._specs_from_swarm(swarm_spec, strategy)

        # 3. Cost-gate
        specs = self._apply_cost_gating(specs)
        if not specs:
            raise RuntimeError("Budget exhausted — cannot dispatch any sub-agents")

        # 4. Dispatch
        if strategy == DispatchStrategy.SEQUENTIAL:
            results = [await self._factory.spawn(s) for s in specs]
        elif strategy == DispatchStrategy.VOTED and len(specs) == 1:
            results = [await self._factory.spawn_voted(specs[0])]
        else:
            results = await self._factory.spawn_parallel(
                specs, max_concurrency=self._max_concurrency
            )

        # 5. Synthesize
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

        fresh_mind_keywords = ("review", "critique", "audit", "verify", "red team")
        if any(kw in lo for kw in fresh_mind_keywords):
            return DispatchStrategy.FRESH_MIND

        voting_keywords = ("security", "financial", "legal", "compliance", "safety")
        if any(kw in lo for kw in voting_keywords):
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
            effective_strategy = (
                DispatchStrategy.FRESH_MIND if cap.requires_fresh_context else strategy
            )
            specs.append(SubAgentSpec(
                role=role,
                description=goal.description,
                prompt=goal.description,
                tier=cap.tier,
                strategy=effective_strategy,
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
            est_tokens = spec.max_tool_calls * 2000
            if self._cost_tracker.can_afford(spec.tier, est_tokens):
                result.append(spec)
            elif self._cost_tracker.can_afford(AgentTier.BUDGET, est_tokens):
                cap = AGENT_CAPABILITIES[spec.role]
                budget_model = next(
                    (m for m in cap.preferred_models if "minimax" in m),
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
            {"role": r.model_used, "summary": r.summary}
            for r in results if r.is_success
        ]
        if not summaries:
            raise RuntimeError("All sub-agents failed — nothing to synthesize")

        return await self._synthesizer.synthesize(
            prompt=original_prompt,
            results=summaries,
            strategy=swarm_spec.synthesis_strategy,
        )
```

**Key changes from original plan:**
1. **`execute()` returns `SwarmResult`** instead of yielding `AgentEvent`. The original plan had the orchestrator yield events, but `SynthesizerAgent.synthesize()` returns `SwarmResult` — not an async generator. Trying to yield from a non-generator was a type error.
2. **`_synthesize()` calls `synthesize(prompt, results, strategy)`** matching the actual signature. The original plan passed `swarm_findings=` which doesn't exist.
3. **Decision gate methods are `@staticmethod`** — no `import re` buried inside a method.
4. **`_map_role` uses enum constructor** with try/except instead of a manually maintained dict that would drift.
5. **Cost gating uses `with_tier()`** to properly downgrade the tier, not just the model.
6. **Removed `_memory` dict** — workflow memory is handled by `WorkflowMemory` model, not an ad-hoc dict.

---

## 5. Application Layer — Flows

### 5.1 `HyperAgentFlow` — `weebot/application/flows/hyper_agent_flow.py`

```python
"""HyperAgentFlow — state machine wrapper for HyperAgent.

Extends BaseFlow with session management and event publishing.
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional, TYPE_CHECKING

from weebot.application.flows.base_flow import BaseFlow
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.sub_agent_cost_tracker_port import SubAgentCostTrackerPort
from weebot.application.ports.sub_agent_factory_port import SubAgentFactoryPort
from weebot.application.ports.swarm_event_bus_port import SwarmEventBusPort
from weebot.application.agents.hyper_agent import HyperAgent
from weebot.domain.models.event import AgentEvent, ErrorEvent, MessageEvent
from weebot.domain.models.session import Session, SessionStatus

if TYPE_CHECKING:
    from weebot.application.cqrs.mediator import Mediator

logger = logging.getLogger(__name__)


class HyperAgentFlow(BaseFlow):

    def __init__(
        self,
        llm: LLMPort,
        session: Session,
        event_bus: EventBusPort,
        swarm_bus: SwarmEventBusPort,
        sub_agent_factory: SubAgentFactoryPort,
        cost_tracker: SubAgentCostTrackerPort,
        model: Optional[str] = None,
        mediator: Optional["Mediator"] = None,
        max_concurrency: int = 4,
        cost_limit_usd: float = 0.50,
    ) -> None:
        self._session = session
        self._event_bus = event_bus
        self._model = model
        self._mediator = mediator
        self._done = False

        self._hyper = HyperAgent(
            llm=llm,
            event_bus=event_bus,
            swarm_bus=swarm_bus,
            sub_agent_factory=sub_agent_factory,
            cost_tracker=cost_tracker,
            model=model,
            max_concurrency=max_concurrency,
            cost_limit_usd=cost_limit_usd,
        )

    async def run(self, prompt: str) -> AsyncGenerator[AgentEvent, None]:
        self._session = self._session.set_status(SessionStatus.RUNNING)
        logger.info("HyperAgentFlow started: session=%s", self._session.id)

        try:
            swarm_result = await self._hyper.execute(prompt)

            event = MessageEvent(
                role="assistant",
                message=swarm_result.synthesis,
            )
            self._session = self._session.add_event(event)
            if self._event_bus:
                await self._event_bus.publish(event)
            yield event

        except Exception as exc:
            logger.exception("HyperAgentFlow failed: %s", exc)
            yield ErrorEvent(error=str(exc))

        self._session = self._session.set_status(SessionStatus.COMPLETED)
        self._done = True

    def is_done(self) -> bool:
        return self._done
```

**Changes from original plan:**
- The flow wraps `HyperAgent.execute()` (which returns `SwarmResult`) and converts it to a single `MessageEvent` yield, satisfying the `BaseFlow` contract of `AsyncGenerator[AgentEvent, None]`.
- Accesses `swarm_result.synthesis` — the text field on `SwarmResult`.

---

## 6. Application Layer — CQRS

### 6.1 Commands — `weebot/application/cqrs/commands/hyper_commands.py`

```python
"""CQRS commands for HyperAgent workflows."""
from __future__ import annotations

from pydantic import Field

from weebot.application.cqrs.base import Command


class DecomposeTaskCommand(Command):
    session_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    model: str = Field(default="minimax/minimax-m3")
    max_sub_agents: int = Field(default=8, ge=1, le=20)


class DispatchSubAgentsCommand(Command):
    session_id: str = Field(min_length=1)
    specs: list[dict] = Field(min_length=1, max_length=20)
    max_concurrency: int = Field(default=4, ge=1, le=8)
    cost_limit_usd: float = Field(default=0.50, ge=0.0)


class SynthesizeResultsCommand(Command):
    session_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    results: list[dict] = Field(min_length=1)
    strategy: str = Field(default="cluster")
```

**Changes from original plan:**
- Added `prompt` to `SynthesizeResultsCommand` — `SynthesizerAgent.synthesize()` requires the original prompt.
- Removed `swarm_findings` — the synthesizer doesn't accept this parameter.

### 6.2 Handlers — `weebot/application/cqrs/handlers/hyper_handlers.py`

```python
"""CQRS handlers for HyperAgent commands."""
from __future__ import annotations

import logging

from weebot.application.cqrs.base import CommandResult
from weebot.application.cqrs.commands.hyper_commands import (
    DecomposeTaskCommand,
    DispatchSubAgentsCommand,
    SynthesizeResultsCommand,
)
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.sub_agent_cost_tracker_port import SubAgentCostTrackerPort
from weebot.application.ports.sub_agent_factory_port import SubAgentFactoryPort
from weebot.application.agents.goal_agent import GoalAgent
from weebot.application.agents.synthesizer_agent import SynthesizerAgent
from weebot.domain.models.sub_agent import SubAgentSpec

logger = logging.getLogger(__name__)


class DecomposeTaskHandler:
    def __init__(self, llm: LLMPort) -> None:
        self._goal_agent = GoalAgent(llm=llm)

    async def handle(self, command: DecomposeTaskCommand) -> CommandResult:
        try:
            swarm_spec = await self._goal_agent.decompose(
                command.prompt, max_goals=command.max_sub_agents
            )
            return CommandResult.ok(swarm_spec.model_dump())
        except Exception as exc:
            return CommandResult.fail(str(exc))


class DispatchSubAgentsHandler:
    def __init__(
        self,
        sub_agent_factory: SubAgentFactoryPort,
        cost_tracker: SubAgentCostTrackerPort,
    ) -> None:
        self._factory = sub_agent_factory
        self._cost_tracker = cost_tracker

    async def handle(self, command: DispatchSubAgentsCommand) -> CommandResult:
        try:
            specs = [SubAgentSpec(**s) for s in command.specs]
            results = await self._factory.spawn_parallel(
                specs, max_concurrency=command.max_concurrency
            )
            return CommandResult.ok({
                "results": [r.model_dump() for r in results],
                "cost_summary": self._cost_tracker.summary(),
            })
        except Exception as exc:
            return CommandResult.fail(str(exc))


class SynthesizeResultsHandler:
    def __init__(self, llm: LLMPort) -> None:
        self._synthesizer = SynthesizerAgent(llm=llm)

    async def handle(self, command: SynthesizeResultsCommand) -> CommandResult:
        try:
            swarm_result = await self._synthesizer.synthesize(
                prompt=command.prompt,
                results=command.results,
                strategy=command.strategy,
            )
            return CommandResult.ok(swarm_result.model_dump())
        except Exception as exc:
            return CommandResult.fail(str(exc))
```

**Changes from original plan:**
- Handler `handle()` methods now use **typed command parameters** instead of `Any`.
- `SynthesizeResultsHandler` calls `synthesize(prompt=..., results=..., strategy=...)` matching the real signature (returns `SwarmResult`, not an async generator).

---

## 7. Infrastructure Layer — Adapters

### 7.1 `SubAgentFactory` — `weebot/infrastructure/adapters/sub_agent_factory.py`

```python
"""Sub-agent factory — spawns PlanActFlow instances as ephemeral sub-agents."""
from __future__ import annotations

import asyncio
import logging
import time as _time
import uuid
from typing import Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.ports.sub_agent_cost_tracker_port import SubAgentCostTrackerPort
from weebot.application.ports.sub_agent_factory_port import SubAgentFactoryPort
from weebot.application.ports.swarm_event_bus_port import SwarmEventBusPort
from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.domain.models.agent_capability import AGENT_CAPABILITIES
from weebot.domain.models.inter_agent import InterAgentMessage
from weebot.domain.models.session import Session
from weebot.domain.models.sub_agent import (
    DispatchStrategy,
    SubAgentResult,
    SubAgentSpec,
    SubAgentStatus,
)
from weebot.tools.tool_registry import RoleBasedToolRegistry

logger = logging.getLogger(__name__)


class SubAgentFactory(SubAgentFactoryPort):

    def __init__(
        self,
        llm: LLMPort,
        state_repo: StateRepositoryPort,
        swarm_bus: SwarmEventBusPort,
        cost_tracker: SubAgentCostTrackerPort,
        tool_registry: Optional[RoleBasedToolRegistry] = None,
    ) -> None:
        self._llm = llm
        self._state_repo = state_repo
        self._swarm_bus = swarm_bus
        self._cost_tracker = cost_tracker
        self._tool_registry = tool_registry or RoleBasedToolRegistry()

    async def spawn(self, spec: SubAgentSpec) -> SubAgentResult:
        cap = AGENT_CAPABILITIES[spec.role]
        session = self._make_session(spec)
        tools = self._tool_registry.create_tool_collection_from_names(
            spec.tools or cap.default_tools
        )

        context_prompt = spec.prompt
        if spec.strategy == DispatchStrategy.FRESH_MIND:
            context_prompt = (
                f"Review task (clean context, no prior conversation):\n\n"
                f"{spec.prompt}"
            )

        flow = PlanActFlow(
            llm=self._llm,
            tools=tools,
            session=session,
            model=spec.model or (cap.preferred_models[0] if cap.preferred_models else None),
            max_step_repetitions=spec.max_tool_calls,
        )

        t0 = _time.monotonic()
        tool_count = 0
        summary = ""

        try:
            async with asyncio.timeout(spec.timeout_seconds):
                async for event in flow.run(context_prompt):
                    if event.type == "tool":
                        tool_count += 1
                    if event.type == "message" and getattr(event, "role", "") == "assistant":
                        summary = getattr(event, "message", "")

            elapsed = _time.monotonic() - t0
            result = SubAgentResult(
                spec_id=spec.id,
                agent_id=session.id,
                status=SubAgentStatus.COMPLETED,
                summary=summary[:2000] if summary else "(no output)",
                model_used=spec.model or cap.preferred_models[0],
                tool_calls=tool_count,
                elapsed_seconds=elapsed,
            )

            await self._swarm_bus.publish(InterAgentMessage(
                sender_agent_id=session.id,
                topic=f"agent_completed.{spec.role.value}",
                payload=result.model_dump(),
                confidence=0.8,
            ))
            return result

        except TimeoutError:
            return SubAgentResult(
                spec_id=spec.id,
                agent_id=session.id,
                status=SubAgentStatus.TIMED_OUT,
                error=f"Timed out after {spec.timeout_seconds}s",
                elapsed_seconds=_time.monotonic() - t0,
            )
        except Exception as exc:
            return SubAgentResult(
                spec_id=spec.id,
                agent_id=session.id,
                status=SubAgentStatus.FAILED,
                error=str(exc),
                elapsed_seconds=_time.monotonic() - t0,
            )

    async def spawn_parallel(
        self, specs: list[SubAgentSpec], max_concurrency: int = 4
    ) -> list[SubAgentResult]:
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _run_one(spec: SubAgentSpec) -> SubAgentResult:
            async with semaphore:
                return await self.spawn(spec)

        return list(await asyncio.gather(*[_run_one(s) for s in specs]))

    async def spawn_voted(
        self, spec: SubAgentSpec, models: list[str] | None = None
    ) -> SubAgentResult:
        models = models or ["minimax/minimax-m3", "qwen/qwen3.7-max", "deepseek/deepseek-v4-pro"]
        specs = [spec.with_model(m) for m in models[:3]]
        results = await self.spawn_parallel(specs, max_concurrency=3)
        return self._select_consensus(results)

    @staticmethod
    def _select_consensus(results: list[SubAgentResult]) -> SubAgentResult:
        completed = [r for r in results if r.is_success]
        if not completed:
            return results[0]
        # v1: return first success. v2: implement pairwise summary similarity.
        return completed[0]

    @staticmethod
    def _make_session(spec: SubAgentSpec) -> Session:
        session_id = f"sub-{spec.role.value}-{uuid.uuid4().hex[:8]}"
        return Session(
            id=session_id,
            user_id="hyper_agent",
            agent_id=f"sub-agent-{spec.role.value}",
            context={
                "sub_agent_role": spec.role.value,
                "sub_agent_spec_id": spec.id,
                "strategy": spec.strategy.value,
            },
        )
```

**Key changes from original plan:**

1. **`spawn()` returns `SubAgentResult`** — no longer an async generator. The original plan yielded `SubAgentResult` as an event which is a type violation (`SubAgentResult` is not `AgentEvent`).

2. **`asyncio.timeout()` wraps the flow** — the original plan caught `asyncio.TimeoutError` but never actually set a timeout. Now uses `asyncio.timeout(spec.timeout_seconds)` (Python 3.11+). Catches `TimeoutError` (the base class in 3.11+).

3. **`swarm_bus.publish(message)`** — calls with `InterAgentMessage` directly (matching the concrete `SwarmEventBus.publish(message)` and the corrected port). The original plan called `publish(topic=..., message=...)` which matched neither the port nor the adapter.

4. **`PlanActFlow` constructor uses `max_step_repetitions`** — the actual parameter name, not `max_steps` which doesn't exist on `PlanActFlow`.

5. **`spawn_parallel` returns `list[SubAgentResult]`** from `asyncio.gather()` — cleaner than appending to a shared mutable list from coroutines.

6. **Renamed `_majority_vote` to `_select_consensus`** with honest docstring — the original claimed "majority vote" but just returned the first success.

### 7.2 `SubAgentCostTracker` — `weebot/infrastructure/adapters/sub_agent_cost_tracker.py`

Unchanged from original plan. The implementation is correct and straightforward.

### 7.3 `SwarmEventBus` — MODIFY `weebot/infrastructure/swarm_event_bus.py`

The concrete adapter already has `publish(message)`, `get_history(topic)`, and `get_all_topics()`. **Required change:** make it implement the updated `SwarmEventBusPort`:

```python
# Add to class declaration:
from weebot.application.ports.swarm_event_bus_port import SwarmEventBusPort

class SwarmEventBus(SwarmEventBusPort):
    # ... existing implementation ...

    async def close(self) -> None:
        self._queues.clear()
        self._history.clear()
```

The `subscribe()` method signature needs a thin wrapper — the port defines `subscribe(topic, handler)` but the concrete class returns a `SwarmSubscription`. Add an adapter method or update the port's `subscribe` to match.

---

## 8. Tool Layer — Agent Tools

### 8.1 Updated Role Mappings — `weebot/tools/tool_registry.py`

Add to `DEFAULT_ROLE_MAPPINGS` (these roles don't exist yet):

```python
"coder": [
    "bash", "python_execute", "file_editor", "web_search",
],
"designer": [
    "image_gen", "file_editor", "browser_inspector",
],
"reviewer": [
    "file_editor", "web_search", "knowledge",
],
"planner_sub": [
    "file_editor", "knowledge", "web_search",
],
```

### 8.2 Updated Tool Tiers — `weebot/tools/tool_registry.py`

Add to `TOOL_TIERS`:

```python
"image_gen": "controlled",
"dispatch_parallel_tasks": "restricted",
"swarm": "restricted",
"workflow_orchestrator": "restricted",
```

---

## 9. DI Container — Wiring

### 9.1 Add to `weebot/application/di/__init__.py`

```python
def configure_defaults(self, *, db_path="./weebot_sessions.db", default_model=None):
    # ... existing registrations ...

    # Multi-agent infrastructure
    from weebot.infrastructure.swarm_event_bus import SwarmEventBus
    from weebot.infrastructure.adapters.sub_agent_cost_tracker import SubAgentCostTracker
    from weebot.infrastructure.adapters.sub_agent_factory import SubAgentFactory

    self.register(SwarmEventBusPort, lambda: SwarmEventBus())
    self.register(SubAgentCostTrackerPort, lambda: SubAgentCostTracker(budget_limit_usd=0.50))
    self.register(SubAgentFactoryPort, lambda: SubAgentFactory(
        llm=self.get(LLMPort),
        state_repo=self.get(StateRepositoryPort),
        swarm_bus=self.get(SwarmEventBusPort),
        cost_tracker=self.get(SubAgentCostTrackerPort),
    ))


def build_hyper_agent_flow(
    self,
    session: Session,
    model: str | None = None,
    max_concurrency: int = 4,
    cost_limit: float = 0.50,
) -> "HyperAgentFlow":
    from weebot.application.flows.hyper_agent_flow import HyperAgentFlow
    return HyperAgentFlow(
        llm=self.get(LLMPort),
        session=session,
        event_bus=self.get(EventBusPort),
        swarm_bus=self.get(SwarmEventBusPort),
        sub_agent_factory=self.get(SubAgentFactoryPort),
        cost_tracker=self.get(SubAgentCostTrackerPort),
        model=model,
        max_concurrency=max_concurrency,
        cost_limit_usd=cost_limit,
    )
```

**Changes from original plan:**
- Removed `mediator=self._maybe_get(Mediator)` — this method doesn't exist on the container. The mediator can be wired later if needed.

---

## 10. CLI — Entry Points

### 10.1 `cli/commands/hyper.py`

```python
"""HyperAgent CLI commands."""
import asyncio
import uuid

import click
from rich.console import Console

from weebot.application.di import Container
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session

console = Console()


@click.group()
def hyper() -> None:
    """Multi-agent workflow commands."""
    pass


@hyper.command("run")
@click.argument("prompt")
@click.option("--session-id", default=None)
@click.option("--model", default=None)
@click.option("--concurrency", default=4)
@click.option("--budget", default=0.50)
def hyper_run(
    prompt: str,
    session_id: str | None,
    model: str | None,
    concurrency: int,
    budget: float,
) -> None:
    """Execute a task using multi-agent orchestration."""
    async def _run() -> None:
        container = Container()
        container.configure_defaults()

        sid = session_id or str(uuid.uuid4())
        state_repo = container.get(StateRepositoryPort)
        session = await state_repo.load_session(sid)
        if session is None:
            session = Session(id=sid, user_id="cli", agent_id="hyper")

        flow = container.build_hyper_agent_flow(
            session=session,
            model=model,
            max_concurrency=concurrency,
            cost_limit=budget,
        )

        console.print(f"[bold blue]HyperAgent[/bold blue] session={sid} concurrency={concurrency} budget=${budget:.2f}")

        async for event in flow.run(prompt):
            if hasattr(event, "message"):
                console.print(event.message)
            elif hasattr(event, "error"):
                console.print(f"[red]{event.error}[/red]")

    asyncio.run(_run())
```

**Changes from original plan:**
- Creates a proper `Session` object instead of `type('S', (), {...})()` hack.
- Simplified event rendering — the original imported `WaitForUserEvent` and `CLIEventSubscriber` without verifying they existed with compatible signatures.

Register in `cli/main.py`:
```python
from cli.commands.hyper import hyper as hyper_group
cli.add_command(hyper_group)
```

---

## 11. System Prompts

### 11.1 Append to `weebot/config/prompts/executor_system.txt`

```
<sub_agent_rules>
You have access to sub-agent tools: dispatch_parallel_tasks, swarm, workflow_orchestrator.

USE SUB-AGENTS WHEN:
1. PARALLELIZATION: 3+ independent sub-tasks that can run concurrently.
   Example: "Research pricing for 5 competitors" → dispatch_parallel_tasks.
2. FRESH MIND: You need unbiased review of content you generated.
   Example: "Review the code I wrote for security" → spawn reviewer sub-agent.

DO NOT USE SUB-AGENTS WHEN:
- Single-operation tasks (≤5 tool calls) — do it yourself.
- Tasks that depend on prior step results — execute sequentially.
- Tasks where your conversation context is essential.

COST RULES:
- Sub-agents cost tokens. Never spawn for trivial tasks.
- Budget-tier roles (reviewer, planner) always use free models.
- Prefer minimax/minimax-m3 for sub-agents when quality permits.
</sub_agent_rules>
```

---

## 12. Testing Strategy

### 12.1 Unit Tests

| Test File | What It Tests |
|-----------|---------------|
| `tests/unit/domain/test_sub_agent_models.py` | `SubAgentSpec` frozen, validation (min_length), `with_model/with_tier/with_strategy`, serialization round-trip |
| `tests/unit/domain/test_agent_capability.py` | Every `SubAgentRole` has a `AGENT_CAPABILITIES` entry; tools reference valid tool names |
| `tests/unit/application/test_hyper_agent.py` | `_classify_task` decision gate, `_specs_from_swarm`, `_apply_cost_gating` (budget → downgrade, exhausted → skip) |
| `tests/unit/application/test_hyper_handlers.py` | CQRS handlers with mocked ports |
| `tests/unit/infrastructure/test_sub_agent_factory.py` | `spawn` returns correct status on success/timeout/failure; `spawn_parallel` respects concurrency |
| `tests/unit/infrastructure/test_sub_agent_cost_tracker.py` | Budget enforcement, tier estimation, `remaining_budget` accuracy |

### 12.2 Integration Tests

| Test File | What It Tests |
|-----------|---------------|
| `tests/integration/test_hyper_agent_flow.py` | End-to-end with mock LLM — verify `SwarmResult` returned through flow |
| `tests/integration/test_parallel_dispatch.py` | Verify concurrency semaphore actually limits parallel execution |
| `tests/integration/test_swarm_bus_integration.py` | Factory publishes to bus; messages retrievable via `get_history` |

### 12.3 Eval Harness

```python
EVAL_PROMPTS = [
    # (prompt, expected_strategy)
    ("Research 5 competitors in parallel", DispatchStrategy.PARALLEL),
    ("Write a hello world function", DispatchStrategy.PARALLEL),  # default
    ("Review this code for bugs", DispatchStrategy.FRESH_MIND),
    ("Calculate the sum of sales.csv", DispatchStrategy.PARALLEL),  # default
    ("Audit the security of our auth module", DispatchStrategy.VOTED),
]
```

---

## 13. Migration & Rollout

### Phase 1 — Domain + Ports (Day 1)

| Step | Files | Verification |
|------|-------|-------------|
| 1.1 | Create `sub_agent.py`, `agent_capability.py`, `workflow_memory.py` domain models | `pytest tests/unit/domain/test_sub_agent_models.py` |
| 1.2 | Create `SubAgentFactoryPort`, `SubAgentCostTrackerPort` | Import check |
| 1.3 | Update `SwarmEventBusPort` — remove `[DEPRECATED]`, add `get_history`, `get_all_topics`, fix `publish` signature | Import check |

### Phase 2 — Infrastructure (Day 2)

| Step | Files | Verification |
|------|-------|-------------|
| 2.1 | Make `SwarmEventBus` implement updated `SwarmEventBusPort`, add `close()` | `pytest tests/unit/infrastructure/test_swarm_event_bus.py` |
| 2.2 | Implement `SubAgentFactory` and `SubAgentCostTracker` | `pytest tests/unit/infrastructure/` |
| 2.3 | Wire into DI container | `python -c "from weebot.application.di import Container; c=Container(); c.configure_defaults()"` |

### Phase 3 — HyperAgent + Flow (Days 3-4)

| Step | Files | Verification |
|------|-------|-------------|
| 3.1 | Implement `HyperAgent` | `pytest tests/unit/application/test_hyper_agent.py` |
| 3.2 | Implement `HyperAgentFlow` | Integration test with mock LLM |
| 3.3 | Add CQRS commands + handlers | `pytest tests/unit/application/test_hyper_handlers.py` |
| 3.4 | Add tool registry entries | Verify roles resolve |

### Phase 4 — Entry Points + Eval (Days 5-6)

| Step | Files | Verification |
|------|-------|-------------|
| 4.1 | `cli/commands/hyper.py` + register in `cli/main.py` | `python -B -m cli.main hyper run "test"` |
| 4.2 | Update `executor_system.txt` | Prompt inspection |
| 4.3 | Eval harness with decision gate test cases | Baseline score |
| 4.4 | Cost tracking validation | Budget enforcement end-to-end |

---

## Appendix A: Codebase Alignment Notes

Issues found during audit (2026-06-06) and how this plan addresses them:

| Issue | Original Plan | Fix |
|-------|---------------|-----|
| `SubAgentSpec.description` had `default=""` + `min_length=1` | Contradictory — instantiation would fail | Made `description` and `prompt` required (no default) |
| `SubAgentResult.findings: list[InterAgentMessage]` | Circular domain dependency | Removed — findings live on SwarmEventBus |
| `spawn()` returned `AsyncGenerator` but yielded `SubAgentResult` (not an `AgentEvent`) | Type violation | `spawn()` returns `SubAgentResult` directly |
| `SwarmEventBusPort.publish(topic, message)` vs `SwarmEventBus.publish(message)` | Signature mismatch | Aligned to `publish(message: InterAgentMessage)` |
| `SwarmEventBusPort` marked `[DEPRECATED]`, missing `get_history`/`get_all_topics` | Plan claimed "no changes needed" | Un-deprecated, added missing methods |
| `SynthesizerAgent.synthesize()` returns `SwarmResult`, not `AsyncGenerator` | Plan treated it as async generator | `HyperAgent.execute()` returns `SwarmResult` |
| `SynthesizerAgent.synthesize()` signature is `(prompt, results, strategy)` | Plan passed `swarm_findings=` (doesn't exist) | Fixed call signature |
| `PlanActFlow.__init__` param is `max_step_repetitions`, not `max_steps` | Would crash at runtime | Fixed parameter name |
| `_majority_vote` returned first success, not actual vote | Misleading name | Renamed `_select_consensus`, honest docstring |
| CLI created `type('S', (), {...})()` hack session | Would break any method expecting `Session` | Creates proper `Session` object |
| Models lacked `ConfigDict(frozen=True)` | Claimed "immutable" but wasn't enforced | Added to all new models |
| `_apply_cost_gating` only changed model, not tier | Downgraded model but cost tracker still saw STANDARD tier | Uses `with_tier(AgentTier.BUDGET)` |
| No `asyncio.timeout` wrapping sub-agent execution | `timeout_seconds` field existed but was never enforced | Added `async with asyncio.timeout()` |
| `_maybe_get(Mediator)` called in DI wiring | Method doesn't exist on container | Removed |

## Appendix B: Industry Best Practices

| Practice | How Applied |
|----------|------------|
| **Dependency Inversion** | All HyperAgent dependencies are injected ports |
| **Frozen Domain Models** | `ConfigDict(frozen=True)` + `model_copy()` for transitions |
| **CQRS** | State mutations via `Mediator.send(command)` with typed handlers |
| **Single Responsibility** | HyperAgent orchestrates, Factory spawns, Synthesizer merges |
| **Open/Closed** | New roles extend `AGENT_CAPABILITIES` dict — no code changes |
| **Fail Fast** | `asyncio.timeout()`, cost budget enforcement, typed validation |
| **Observability** | Lifecycle events via `EventBusPort`, findings via `SwarmEventBusPort` |
| **Cost Awareness** | `SubAgentCostTrackerPort` with tier-based estimation and downgrade |
| **Test Pyramid** | Unit (frozen models) → Integration (mock LLM flows) → Eval (decision quality) |

## Appendix C: File Manifest

| File | Status | Purpose |
|------|--------|---------|
| `weebot/domain/models/sub_agent.py` | **New** | `SubAgentSpec`, `SubAgentResult`, enums |
| `weebot/domain/models/agent_capability.py` | **New** | `AgentCapability`, `AGENT_CAPABILITIES` registry |
| `weebot/domain/models/workflow_memory.py` | **New** | `WorkflowMemory`, `MemoryEntry` |
| `weebot/application/ports/sub_agent_factory_port.py` | **New** | `SubAgentFactoryPort` ABC |
| `weebot/application/ports/sub_agent_cost_tracker_port.py` | **New** | `SubAgentCostTrackerPort` ABC |
| `weebot/application/ports/swarm_event_bus_port.py` | **Modify** | Un-deprecate, align `publish` signature, add `get_history`/`get_all_topics` |
| `weebot/application/agents/hyper_agent.py` | **New** | `HyperAgent` orchestrator |
| `weebot/application/flows/hyper_agent_flow.py` | **New** | `HyperAgentFlow` state machine |
| `weebot/application/cqrs/commands/hyper_commands.py` | **New** | CQRS commands |
| `weebot/application/cqrs/handlers/hyper_handlers.py` | **New** | CQRS handlers |
| `weebot/infrastructure/adapters/sub_agent_factory.py` | **New** | `SubAgentFactory` concrete |
| `weebot/infrastructure/adapters/sub_agent_cost_tracker.py` | **New** | `SubAgentCostTracker` concrete |
| `weebot/infrastructure/swarm_event_bus.py` | **Modify** | Implement `SwarmEventBusPort`, add `close()` |
| `weebot/tools/tool_registry.py` | **Modify** | Add coder/designer/reviewer/planner_sub roles |
| `weebot/application/di/__init__.py` | **Modify** | Wire new ports + `build_hyper_agent_flow()` |
| `cli/commands/hyper.py` | **New** | CLI entry point |
| `cli/main.py` | **Modify** | Register hyper command group |
| `weebot/config/prompts/executor_system.txt` | **Modify** | Add `<sub_agent_rules>` section |
