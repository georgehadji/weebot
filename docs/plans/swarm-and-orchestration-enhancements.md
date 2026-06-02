# Weebot Agent Swarm & Orchestration Enhancements

**Author:** Reasonix Code  
**Date:** 2026-06-02  
**Status:** Draft — pending review  
**Source:** Audit of `transcript_merged.txt` (Sean's AI Stories — Agent Teams vs Agent Swarm)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Compliance](#architecture-compliance)
3. [Phase 1 — Goal-Driven Agent Swarm (`swarm` tool)](#phase-1--goal-driven-agent-swarm-swarm-tool)
4. [Phase 2 — Leader Agent Orchestration](#phase-2--leader-agent-orchestration)
5. [Phase 3 — Opposing-Viewpoints Synthesis (`debate` tool)](#phase-3--opposing-viewpoints-synthesis-debate-tool)
6. [Phase 4 — Competitive Landscape Analysis Skill](#phase-4--competitive-landscape-analysis-skill)
7. [Phase 5 — Mid-Execution Steering](#phase-5--mid-execution-steering)
8. [Dependency Graph](#dependency-graph)
9. [Risk Assessment](#risk-assessment)
10. [Rollout Strategy](#rollout-strategy)

---

## Executive Summary

This plan defines 5 enhancements that close the gap between weebot's current single-agent PlanActFlow architecture and the multi-agent orchestration patterns demonstrated by Claude Code (agent teams) and Kimi K2.5 (agent swarms).

**Total estimated effort:** ~2,800 lines of new code across 14 files.  
**Total new dependencies:** 0 (all leverage existing infrastructure).  
**Architecture:** Every phase respects weebot's Clean Architecture — domain models first, ports as contracts, adapters in infrastructure, orchestration in application.

---

## Architecture Compliance

### Principles (non-negotiable)

1. **Domain-first.** New concepts start as Pydantic models in `weebot/domain/models/`. No infrastructure details leak into domain.
2. **Ports before adapters.** Any new I/O surface (streaming input, agent-to-agent messages) gets an abstract port in `weebot/application/ports/` before any implementation.
3. **CQRS for mutations.** Agent spawning, swarm lifecycle, and debate synthesis flow through the Mediator with pipeline behaviors (logging, validation, telemetry, save-policy).
4. **Tool contract.** Every new agent capability is a `BaseTool` subclass registered in `RoleBasedToolRegistry`. No exception.
5. **Immutable state.** Session mutations use `model_copy(update={...})` — never in-place mutation.

### Layers touched

```
interfaces/          ← new CLI commands, WebSocket steering channel
application/
  flows/             ← LeaderActFlow (new), SwarmOrchestrator (new)
  agents/            ← GoalAgent, SynthesizerAgent, DebateAgent (new)
  cqrs/              ← SwarmSpawnCommand, DebateCommand (new)
  ports/             ← SteeringPort (new)
  services/          ← SwarmDecomposer, ViewpointReconciler (new)
domain/
  models/            ← SwarmSpec, DebateResult, LeaderPlan (new)
infrastructure/
  adapters/          ← StreamingInputAdapter (new)
tools/               ← swarm.py, debate.py (new)
skills/builtin/      ← competitive_analysis/ (new)
```

---

## Phase 1 — Goal-Driven Agent Swarm (`swarm` tool)

### What it does

User provides a vague/high-level prompt. A goal agent decomposes it into sub-goals, auto-generates agent roles with tool assignments, spawns them via `dispatch_parallel_tasks`, and a synthesizer clusters results into a structured deliverable.

Mimics Kimi K2.5's agent swarm pattern.

### Domain models

**`weebot/domain/models/swarm.py`** (new)

```python
from pydantic import BaseModel, Field
from typing import Optional

class SubGoal(BaseModel):
    """A single decomposed sub-goal from the goal agent."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str                          # "Research competitor pricing"
    role: str                                  # "pricing_analyst"
    tools: list[str] = Field(default_factory=list)  # ["web_search", "advanced_browser"]
    priority: int = 0                          # 0 = highest

class SwarmSpec(BaseModel):
    """Complete swarm decomposition produced by the goal agent."""
    original_prompt: str
    goals: list[SubGoal]
    max_concurrency: int = 4
    synthesis_strategy: str = "cluster"        # "cluster" | "merge" | "vote"

class SwarmResult(BaseModel):
    """Aggregated result from a swarm execution."""
    prompt: str
    sub_results: list[dict]                    # [{goal_id, agent_role, summary, artifacts}]
    clusters: list[dict]                       # [{label, members, insight}]
    synthesis: str                             # final human-readable report
    token_cost: float
    elapsed_seconds: float
```

### Application layer

**`weebot/application/agents/goal_agent.py`** (new)

```python
class GoalAgent:
    """Decomposes a high-level prompt into a SwarmSpec via a single LLM call.
    
    Uses structured output (Pydantic model) via the existing planner pattern.
    Model: MODEL_CASCADE_TIER1 (Owl Alpha — free, agentic).
    """
    
    async def decompose(self, prompt: str, max_goals: int = 8) -> SwarmSpec:
        """Return a SwarmSpec with auto-generated roles and tool assignments."""
```

**`weebot/application/agents/synthesizer_agent.py`** (new)

```python
class SynthesizerAgent:
    """Clusters and merges results from parallel swarm agents.
    
    Implements the 'clustering agent' pattern from the transcript:
    - Groups related findings by topic
    - Identifies consensus and dissent
    - Produces a structured report with citations
    """
    
    async def synthesize(self, results: list[dict], strategy: str) -> SwarmResult:
```

**`weebot/application/cqrs/commands/swarm_commands.py`** (new)

```python
@dataclass
class SpawnSwarmCommand:
    """CQRS command: decompose prompt → spawn agents → collect results."""
    session_id: str
    prompt: str
    max_concurrency: int = 4
    max_goals: int = 8
```

**Handler:** `SwarmSpawnHandler` — calls GoalAgent.decompose() → dispatches via existing `DispatchAgentsTool` → calls SynthesizerAgent.synthesize().

### Tool

**`weebot/tools/swarm.py`** (new)

```python
class SwarmTool(BaseTool):
    name: str = "swarm"
    description: str = (
        "Decompose a complex task into sub-goals, spawn parallel agents "
        "with auto-generated roles, and synthesize results. Best for research, "
        "competitive analysis, and open-ended exploration where you don't know "
        "in advance what sub-tasks are needed."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "max_goals": {"type": "integer", "default": 8},
            "max_concurrency": {"type": "integer", "default": 4},
        },
        "required": ["prompt"],
    }
```

Registered in `RoleBasedToolRegistry` under `admin` and `researcher` roles.

### What already exists (reused)

| Component | File | Reuse |
|-----------|------|-------|
| `dispatch_parallel_tasks` | `weebot/tools/dispatch_agents.py` | Spawning sub-agents concurrently |
| `PlannerAgent` structured output | `weebot/application/agents/planner.py` | Pattern for LLM → Pydantic parsing |
| `ToolCollection` | `weebot/application/models/tool_collection.py` | Tool dispatch by name |
| `Session` ephemeral creation | `weebot/domain/models/session.py` | Sub-agent session isolation |

### Files changed/created

| File | Action | Lines |
|------|--------|-------|
| `weebot/domain/models/swarm.py` | Create | ~50 |
| `weebot/application/agents/goal_agent.py` | Create | ~80 |
| `weebot/application/agents/synthesizer_agent.py` | Create | ~100 |
| `weebot/application/cqrs/commands/swarm_commands.py` | Create | ~30 |
| `weebot/application/cqrs/handlers.py` | Modify (+1 handler) | ~60 |
| `weebot/tools/swarm.py` | Create | ~80 |
| `weebot/tools/tool_registry.py` | Modify (+1 entry) | ~5 |
| **Total** | | **~405** |

---

## Phase 2 — Leader Agent Orchestration

### What it does

A new flow (`LeaderActFlow`) extends `PlanActFlow` with a leader-agent pattern: the leader plans a task, delegates sub-steps to specialized sub-agents (each running their own `PlanActFlow`), monitors progress, handles failures, and merges results. Accepts mid-execution steering.

Mimics Claude Code's agent teams pattern with a team lead.

### Domain models

**`weebot/domain/models/leader_plan.py`** (new)

```python
class LeaderTask(BaseModel):
    """A task the leader delegates to a worker agent."""
    id: str
    description: str
    assigned_role: str               # maps to RoleBasedToolRegistry role
    status: TaskStatus               # PENDING → DISPATCHED → RUNNING → DONE | FAILED
    assigned_agent_id: Optional[str] # session_id of the worker
    result_summary: Optional[str]
    dependencies: list[str] = []     # task IDs that must complete first

class LeaderPlan(BaseModel):
    """Full delegation plan from the leader agent."""
    title: str
    tasks: list[LeaderTask]
    merge_strategy: str = "sequential"  # "sequential" | "dag" | "parallel"
    leader_notes: str = ""
```

### Application layer

**`weebot/application/flows/leader_act_flow.py`** (new)

Extends `BaseFlow`. States: `Planning → Delegating → Monitoring → Merging → Completed`.

- **Planning:** Leader agent (LLM call) produces a `LeaderPlan` with task decomposition, role assignments, and dependency ordering.
- **Delegating:** Spawns worker sessions via `TaskRunner`, each running `PlanActFlow` with the assigned role's tool set.
- **Monitoring:** Polls worker sessions, handles timeouts/failures, re-delegates failed tasks.
- **Merging:** Collects results, resolves dependencies, produces final deliverable.

**`weebot/application/agents/leader_agent.py`** (new)

```python
class LeaderAgent:
    """Produces a LeaderPlan from a complex prompt.
    
    Different from PlannerAgent: PlannerAgent produces Step lists for
    sequential execution. LeaderAgent produces LeaderTasks with role
    assignments and dependency graphs for parallel delegation.
    """
    
    async def create_leader_plan(self, prompt: str, available_roles: list[str]) -> LeaderPlan:
```

### What already exists (reused)

| Component | Reuse |
|-----------|-------|
| `PlanActFlow` | Each worker runs a full PlanActFlow in its own Session |
| `TaskRunner` | Manages worker session lifecycle (spawn, monitor, cancel) |
| `RoleBasedToolRegistry` | Maps leader-assigned roles to tool sets |
| `DependencyGraph` (`weebot/core/dependency_graph.py`) | DAG validation + topological sort for task ordering |

### Files changed/created

| File | Action | Lines |
|------|--------|-------|
| `weebot/domain/models/leader_plan.py` | Create | ~45 |
| `weebot/application/agents/leader_agent.py` | Create | ~90 |
| `weebot/application/flows/leader_act_flow.py` | Create | ~200 |
| `weebot/application/flows/states/leader_delegating.py` | Create | ~70 |
| `weebot/application/flows/states/leader_monitoring.py` | Create | ~80 |
| `weebot/application/flows/states/leader_merging.py` | Create | ~60 |
| `weebot/interfaces/factories.py` | Modify (+1 flow type) | ~10 |
| `cli/main.py` | Modify (+1 command) | ~30 |
| **Total** | | **~585** |

---

## Phase 3 — Opposing-Viewpoints Synthesis (`debate` tool)

### What it does

Spawn 3 agents with deliberately different perspectives (optimist, pessimist, pragmatist). Each researches the same question independently using their assigned role. A reconciler agent identifies consensus, dissent, and blind spots, producing a balanced analysis.

Key insight from the transcript: *"agents have different opinions because they could have different conclusions individualistically, and then reconcile to avoid bias."*

### Domain models

**`weebot/domain/models/debate.py`** (new)

```python
class Viewpoint(BaseModel):
    """A single perspective in a debate."""
    role: str                       # "optimist" | "pessimist" | "pragmatist"
    research_findings: str
    key_claims: list[str]
    confidence: float               # 0.0–1.0

class DebateResult(BaseModel):
    """Synthesized result from opposing viewpoints."""
    question: str
    viewpoints: list[Viewpoint]
    consensus: list[str]            # points all viewpoints agree on
    dissent: list[dict]             # [{"topic": ..., "optimist": ..., "pessimist": ...}]
    blind_spots: list[str]          # areas no viewpoint covered
    synthesis: str                  # final balanced analysis
    confidence: float               # aggregate confidence
```

### Application layer

**`weebot/application/agents/debate_agent.py`** (new)

```python
class DebateAgent:
    """Orchestrates a multi-perspective analysis.
    
    1. Spawns 3 PerspectiveAgents (optimist/pessimist/pragmatist)
       via dispatch_parallel_tasks
    2. Each PerspectiveAgent researches the question independently
    3. ReconcilerAgent identifies consensus, dissent, blind spots
    4. Produces DebateResult with balanced synthesis
    """
```

### Tool

**`weebot/tools/debate.py`** (new)

```python
class DebateTool(BaseTool):
    name: str = "debate"
    description: str = (
        "Analyze a question from multiple opposing perspectives. "
        "Spawns optimist, pessimist, and pragmatist agents to research "
        "independently, then reconciles findings into a balanced analysis."
    )
```

### What already exists (reused)

| Component | Reuse |
|-----------|-------|
| Phase 1 swarm infrastructure | Goal decomposition + spawn + synthesize pattern |
| `mixture_of_agents` | Existing multi-model synthesis (complementary, not replaced) |
| `dispatch_parallel_tasks` | Concurrent perspective research |

### Files changed/created

| File | Action | Lines |
|------|--------|-------|
| `weebot/domain/models/debate.py` | Create | ~35 |
| `weebot/application/agents/debate_agent.py` | Create | ~120 |
| `weebot/tools/debate.py` | Create | ~70 |
| `weebot/tools/tool_registry.py` | Modify (+1 entry) | ~3 |
| **Total** | | **~228** |

---

## Phase 4 — Competitive Landscape Analysis Skill

### What it does

Encodes the exact research pattern from the transcript as a reusable skill playbook. When the agent is asked to analyze a competitive landscape, it follows a proven workflow: identify competitors → cluster by positioning → find whitespace → generate actionable recommendations.

### Skill definition

**`weebot/skills/builtin/competitive_analysis/SKILL.md`** (new)

```markdown
---
name: competitive_analysis
description: Analyze a competitive landscape using swarm research, clustering,
             and whitespace identification. Based on proven patterns from
             Sean's AI Stories agent swarm research methodology.
metadata:
  emoji: 🔬
---

# Competitive Landscape Analysis

When asked to research a competitive landscape or market position:

## Phase 1: Discovery (use swarm tool)
1. Decompose the research question with `swarm(prompt="...")`
2. Let the goal agent determine sub-goals automatically
3. Target: identify direct competitors, adjacent players, aspirational benchmarks

## Phase 2: Clustering
1. Group competitors by positioning: price tier, target audience, content style
2. For each cluster, extract: common patterns, differentiation strategies
3. Flag: oversaturated segments, underserved niches

## Phase 3: Whitespace Identification
1. Cross-reference: what's EVERYONE doing? (table stakes)
2. Cross-reference: what's NOBODY doing? (opportunity)
3. Cross-reference: what's ONE player doing successfully? (validated whitespace)

## Phase 4: Recommendations
1. Top 3 whitespace opportunities
2. For each: estimated effort, competitive moat potential, time-to-value
3. Concrete next actions (video topics, features, positioning changes)

## Output Format
- Executive summary (3 sentences)
- Competitor cluster map (markdown table)
- Whitespace matrix (markdown table)
- Actionable recommendations (numbered list with effort/impact scores)
```

### What already exists (reused)

| Component | Reuse |
|-----------|-------|
| Phase 1 `swarm` tool | Auto-decomposition + parallel research |
| `competitive_analysis.yaml` template | Already registered in `templates/builtin/` |
| `design_system` tool | Extract visual/positioning data from competitor sites |

### Files changed/created

| File | Action | Lines |
|------|--------|-------|
| `weebot/skills/builtin/competitive_analysis/SKILL.md` | Create | ~80 |
| `weebot/templates/builtin/competitive_analysis.yaml` | Update | ~40 |
| **Total** | | **~120** |

---

## Phase 5 — Mid-Execution Steering

### What it does

Currently `WaitForUserEvent` only fires on explicit `ask_human` tool calls. This enhancement adds an async input channel that lets the user inject feedback at any time during execution (*"spend less time on X"*, *"simplify, use fewer tools"*). The running flow receives the steering as a `SteeringEvent` and adapts its behavior.

Mimics the Claude Code interaction where the user said *"don't overthink, use fewer than 10 tools"* and the leader agent immediately adjusted.

### Port definition

**`weebot/application/ports/steering_port.py`** (new)

```python
from abc import ABC, abstractmethod
from typing import Optional

class SteeringPort(ABC):
    """Non-blocking input channel for mid-execution user feedback."""
    
    @abstractmethod
    async def poll(self, session_id: str) -> Optional[str]:
        """Return any pending steering input, or None."""
        ...
    
    @abstractmethod
    async def send(self, session_id: str, message: str) -> None:
        """Queue a steering message for a running session."""
        ...
```

### Domain models

**`weebot/domain/models/event.py`** (modify — add to AgentEvent union)

```python
class SteeringEvent(BaseEvent):
    """User injected mid-execution feedback."""
    type: Literal["steering"] = "steering"
    session_id: str = ""
    message: str = ""
```

### Application layer

Modify `PlanActFlow.run()` and `ExecutingState.execute()` to check `SteeringPort.poll()` between steps. If steering input is available, inject it as context into the next LLM call:

```python
steering = await self._steering.poll(session_id)
if steering:
    messages.append({
        "role": "user",
        "content": f"[STEERING] The user says: {steering}. Adjust your approach immediately."
    })
```

### Infrastructure

**`weebot/infrastructure/adapters/steering_adapter.py`** (new)

```python
class InMemorySteeringAdapter(SteeringPort):
    """Queue-based steering for CLI/WebSocket use."""
    
    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}
    
    async def poll(self, session_id: str) -> Optional[str]:
        q = self._queues.get(session_id)
        if q and not q.empty():
            return await q.get()
        return None
    
    async def send(self, session_id: str, message: str) -> None:
        if session_id not in self._queues:
            self._queues[session_id] = asyncio.Queue()
        await self._queues[session_id].put(message)
```

### CLI integration

In `run_interactive()`, spawn a background task that reads stdin and routes to `SteeringPort.send()`:

```python
async def _steering_listener(session_id: str, steering: SteeringPort):
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if line.strip():
            await steering.send(session_id, line.strip())
```

Triggered by a hotkey prefix (e.g., typing `>> use fewer tools`).

### WebSocket integration

The existing `/ws/sessions/{session_id}` endpoint already receives messages. Add a handler that routes non-JSON messages to `SteeringPort.send()`.

### What already exists (reused)

| Component | Reuse |
|-----------|-------|
| `WaitForUserEvent` | Existing HITL pattern — steering is the async variant |
| `ConnectionManager` | WebSocket sessions already tracked |
| `EventBusPort` | Steering events published like any other event |

### Files changed/created

| File | Action | Lines |
|------|--------|-------|
| `weebot/application/ports/steering_port.py` | Create | ~25 |
| `weebot/domain/models/event.py` | Modify (+1 event type) | ~8 |
| `weebot/infrastructure/adapters/steering_adapter.py` | Create | ~45 |
| `weebot/application/flows/plan_act_flow.py` | Modify (poll steering) | ~30 |
| `weebot/application/flows/states/executing.py` | Modify (inject steering) | ~20 |
| `weebot/application/di.py` | Modify (+1 binding) | ~5 |
| `run.py` | Modify (+listener task) | ~30 |
| `weebot/interfaces/web/websocket.py` | Modify (+steering route) | ~15 |
| **Total** | | **~178** |

---

## Dependency Graph

```
Phase 5 (Steering) ←── independent, can ship anytime
     |
Phase 1 (Swarm) ←── no dependencies, first to build
     |
     ├── Phase 2 (Leader Agent) ←── depends on Phase 1 (reuses spawn+synthesize)
     |
     ├── Phase 3 (Debate) ←── depends on Phase 1 (reuses swarm infrastructure)
     |
     └── Phase 4 (Competitive Analysis Skill) ←── depends on Phase 1 (uses swarm tool)
```

**Recommended build order:** 5 → 1 → 3 → 4 → 2

Phase 5 is independent and small — ship it first as a quick win. Phase 1 is the foundation. Phases 3 and 4 are thin wrappers around Phase 1. Phase 2 is the largest and depends on Phase 1 being stable.

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|-----------|
| **Token cost explosion** — swarm spawns 8 agents × 25 steps each = 200 LLM calls | HIGH | Hard cap on sub-goals (8). Budget tracking per-swarm via `CostLedger`. Auto-escalate to user if estimated cost > $2. |
| **Swarm quality** — auto-generated roles may be nonsensical | MEDIUM | Goal agent uses structured output with validation. Synthesizer flags low-quality sub-results. |
| **Orphaned sub-agents** — leader crashes, workers keep running | MEDIUM | `TaskRunner` cancellation cascades. Workers bound to leader session; leader cancel → workers cancel. |
| **Steering injection attacks** — user types malicious prompt mid-execution | LOW | Steering text passes through existing `InputSanitizer`. Treated as user input, not code. |
| **Phase 2 complexity** — LeaderActFlow is the largest addition | MEDIUM | Build on existing PlanActFlow, don't replace it. States are additive, not replacement. |

---

## Rollout Strategy

### Milestone 1: Foundation (Week 1)
- Ship Phase 5 (Steering) — smallest, most visible impact
- Ship Phase 1 (Swarm tool) — core infrastructure

### Milestone 2: Thin Wrappers (Week 2)
- Ship Phase 3 (Debate tool) — leverages Phase 1
- Ship Phase 4 (Competitive Analysis skill) — documentation + template

### Milestone 3: Orchestration (Week 3-4)
- Ship Phase 2 (Leader Agent) — most complex, depends on Phase 1 stability

### Post-ship
- 2-week bake period monitoring token costs and swarm quality
- Collect 50+ real swarm traces before tuning GoalAgent prompt
- A/B test leader plan quality vs. manual PlanActFlow on same tasks

---

## Appendix: Example Session Flow (Post-Implementation)

```
User: "Analyze my YouTube channel's competitive position and suggest 3 new video topics"

→ PlanActFlow creates plan:
   Step 1: swarm(prompt="Research AI YouTube channel landscape,
          identify competitors, cluster by content style, find whitespace")
   Step 2: debate(question="What video topics would differentiate
          my channel and attract non-technical founders?")
   Step 3: file_editor(command="create", path="channel_strategy.md")

→ During Step 1, user types: >> focus on Spanish-language market
→ SteeringEvent injected → swarm adds Spanish-market sub-goal

→ Step 1 completes: SwarmResult with 26 channels clustered,
   3 whitespace opportunities, Spanish market insight

→ Step 2 completes: DebateResult — pragmatist view wins,
   recommends "AI for Business Owners" series

→ Step 3: file_editor writes channel_strategy.md with all findings
```
