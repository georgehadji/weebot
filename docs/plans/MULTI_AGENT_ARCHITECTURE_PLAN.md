# Multi-Agent Architecture Plan — HyperAgents, Sub-Agents & Workflows

> Grounded in existing weebot infrastructure: `SwarmSpec`, `GoalAgent`,
> `DispatchAgentsTool`, `AgentFactory`, `AgentContext`, `InterAgentMessage`.

---

## 1. Architecture Overview

```
                        ┌──────────────────────┐
                        │     User Prompt       │
                        └──────────┬───────────┘
                                   │
                        ┌──────────▼───────────┐
                        │    HYPERAGENT         │
                        │  (GoalAgent +         │
                        │   SynthesizerAgent)   │
                        │                       │
                        │  • Decomposes task    │
                        │  • Creates SwarmSpec  │
                        │  • Spawns sub-agents  │
                        │  • Monitors progress  │
                        │  • Synthesizes output │
                        └──┬───────┬───────┬───┘
                           │       │       │
              ┌────────────▼┐ ┌────▼────┐ ┌▼────────────┐
              │ RESEARCHER  │ │ CODER   │ │ DESIGNER     │
              │ sub-agent   │ │ sub-agt │ │ sub-agent    │
              │             │ │         │ │              │
              │ web_search  │ │ bash    │ │ image_gen    │
              │ browser     │ │ python  │ │ file_editor  │
              │ knowledge   │ │ file_ed │ │ browser      │
              └──────┬──────┘ └───┬─────┘ └──────┬───────┘
                     │            │               │
                     └────────────┼───────────────┘
                                  │ InterAgentMessage bus
                     ┌────────────▼───────────────┐
                     │    SYNTHESIZER             │
                     │  • Clusters findings       │
                     │  • Resolves conflicts      │
                     │  • Produces final output   │
                     └────────────────────────────┘
```

## 2. Component Inventory

### 2.1 HyperAgent (`weebot/application/agents/hyper_agent.py`)

**New file.** The top-level orchestrator. One per user task.

| Responsibility | How |
|----------------|-----|
| Task decomposition | Calls `GoalAgent` to produce a `SwarmSpec` with `SubGoal` list |
| Agent spawning | Uses `AgentFactory.spawn_orchestrator_agents()` for parallel dispatch |
| Progress monitoring | Subscribes to `InterAgentMessage` bus; tracks completion |
| Result synthesis | Calls `SynthesizerAgent` to cluster, deduplicate, merge |
| Failure recovery | Re-spawns failed sub-agents with adjusted context |
| User steering | Exposes mid-execution steering via `SteeringPort` |

**Key method:** `HyperAgent.execute(prompt) → AsyncGenerator[AgentEvent, None]`

**State machine:**
```
DECOMPOSING → DISPATCHING → MONITORING → SYNTHESIZING → COMPLETED
                  ↑              │
                  └── RESPAWNING ←┘ (on sub-agent failure)
```

### 2.2 Sub-Agent Roles

Existing roles in `RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS`:

| Role | Tools | Use Case |
|------|-------|----------|
| `researcher` | web_search, vane_search, browser, knowledge, video_ingest | Web research, fact-finding |
| `analyst` | python_execute, file_editor, knowledge, bash | Data analysis, computation |
| `automation` | bash, computer_use, screen_capture, schedule, file_editor | System automation |
| `documentation` | file_editor, knowledge, web_search | Writing, docs, reports |
| `admin` | all tools | Full access (orchestrator only) |

**New roles to add:**

| Role | Tools | Use Case |
|------|-------|----------|
| `coder` | bash, python_execute, file_editor, web_search | Code generation, debugging |
| `designer` | image_gen, file_editor, browser, advanced_browser | UI/UX, image generation, CSS |
| `reviewer` | file_editor, knowledge, web_search | Code review, QA, fact-checking |
| `planner_sub` | file_editor, knowledge, web_search | Sub-planning for complex sub-tasks |

### 2.3 Inter-Agent Communication

Already exists: `InterAgentMessage` (`weebot/domain/models/inter_agent.py`)

```python
InterAgentMessage(
    sender_agent_id: str,
    topic: str,              # e.g. 'competitor_found', 'pricing_discovered'
    payload: dict[str, Any],
    confidence: float,       # 0.0-1.0
    timestamp: datetime,
)
```

**Bus:** `SwarmEventBusPort` → `SwarmEventBus` (existing interface, needs concrete implementation)

**Message flow:**
1. Sub-agent discovers something → publishes `InterAgentMessage`
2. Other sub-agents subscribe to topics → receive relevant findings
3. Synthesizer reads all messages → clusters by topic → produces merged result

### 2.4 Workflow Patterns

Already templated in `weebot/templates/builtin/team_patterns/`:

| Pattern | File | When to Use |
|---------|------|-------------|
| **Fan-out/Fan-in** | `fan_out_fan_in.yaml` | Parallel research, multi-source analysis |
| **Pipeline** | `pipeline.yaml` | Sequential stages (research → analyze → write) |
| **Supervisor** | `supervisor.yaml` | One agent reviews others' output |
| **Hierarchical Delegation** | `hierarchical_delegation.yaml` | Complex tasks with sub-sub-tasks |
| **Expert Pool** | `expert_pool.yaml` | Multiple specialists contribute independently |
| **Producer/Reviewer** | `producer_reviewer.yaml` | Coder produces → reviewer critiques → coder fixes |

## 3. Implementation Plan

### Phase 1 — Foundation (already largely done)

| Component | Status | Location |
|-----------|--------|----------|
| `SwarmSpec` / `SubGoal` | ✅ | `weebot/domain/models/swarm.py` |
| `InterAgentMessage` | ✅ | `weebot/domain/models/inter_agent.py` |
| `GoalAgent` | ✅ | `weebot/application/agents/goal_agent.py` |
| `SynthesizerAgent` | ✅ | `weebot/application/agents/synthesizer_agent.py` |
| `DispatchAgentsTool` | ✅ | `weebot/tools/dispatch_agents.py` |
| `SwarmTool` | ✅ | `weebot/tools/swarm.py` |
| `AgentFactory` | ✅ | `weebot/core/agent_factory.py` |
| `AgentContext` | ✅ | `weebot/core/agent_context.py` |
| `RoleBasedToolRegistry` | ✅ | `weebot/tools/tool_registry.py` |
| Workflow templates | ✅ | `weebot/templates/builtin/team_patterns/` |

### Phase 2 — HyperAgent (new: `weebot/application/agents/hyper_agent.py`)

**Step 2.1:** Create `HyperAgent` class

```python
class HyperAgent:
    """Top-level orchestrator for multi-agent task execution."""

    def __init__(self, llm, tools, event_bus, agent_factory):
        self._goal_agent = GoalAgent(llm=llm)
        self._synthesizer = SynthesizerAgent(llm=llm)
        self._factory = agent_factory
        self._event_bus = event_bus
        self._sub_agents: dict[str, WeebotAgent] = {}
        self._messages: list[InterAgentMessage] = []

    async def execute(self, prompt: str) -> AsyncGenerator[AgentEvent, None]:
        # 1. Decompose
        swarm_spec = await self._goal_agent.decompose(prompt)
        yield SwarmSpecEvent(spec=swarm_spec)

        # 2. Dispatch sub-agents
        for goal in swarm_spec.goals:
            agent = await self._factory.spawn_agent(
                role=goal.role,
                tools_subset=goal.tools,
            )
            self._sub_agents[goal.id] = agent

        # 3. Run in parallel with inter-agent messaging
        results = await self._run_parallel(swarm_spec)

        # 4. Synthesize
        final = await self._synthesizer.synthesize(
            results,
            strategy=swarm_spec.synthesis_strategy,
        )
        yield SwarmResultEvent(result=final)
```

**Step 2.2:** Add `HyperAgentFlow` as a new flow type

`weebot/application/flows/hyper_agent_flow.py` — extends `BaseFlow`, uses the HyperAgent state machine.

**Step 2.3:** Wire into DI container

`Container.build_hyper_agent_flow()` — constructs HyperAgent with all dependencies.

**Step 2.4:** Add CLI command

```bash
python -m cli.main flow hyper "Build a full-stack SaaS app"
```

### Phase 3 — Inter-Agent Communication Bus

**Step 3.1:** Implement `SwarmEventBus`

`weebot/infrastructure/swarm_event_bus.py` — in-process pub/sub for `InterAgentMessage`. Sub-agents publish findings; other sub-agents subscribe by topic.

**Step 3.2:** Topic-based routing

```python
# Researcher publishes:
await bus.publish(InterAgentMessage(
    sender="researcher-1",
    topic="pricing_found",
    payload={"competitor": "X", "price": "$99/mo"},
    confidence=0.9,
))

# Analyst subscribes:
async for msg in bus.subscribe(topic="pricing_found"):
    # Use the finding in analysis
```

**Step 3.3:** Confidence-weighted synthesis

SynthesizerAgent weights findings by confidence score when merging.

### Phase 4 — Sub-Agent Self-Improvement

**Step 4.1:** Failed sub-agent recovery

When a sub-agent fails or times out, HyperAgent re-spawns it with:
- The original goal + error context
- Findings from sibling agents that completed
- Adjusted tools or model if the failure was tool-related

**Step 4.2:** Dynamic re-planning

If a sub-agent discovers something that changes the task scope, it publishes a `scope_change` message. HyperAgent can re-decompose the remaining work.

### Phase 5 — Workflow Template Engine

**Step 5.1:** Template-driven workflows

The HyperAgent reads workflow templates from `weebot/templates/builtin/team_patterns/` and maps them to the task:

```python
workflow = TemplateEngine.select_template(prompt)
# → "fan_out_fan_in" for research tasks
# → "producer_reviewer" for coding tasks
# → "pipeline" for data processing tasks
```

**Step 5.2:** Dynamic pattern selection

The GoalAgent can suggest a workflow pattern based on task analysis:
- Research → fan-out/fan-in
- Coding → producer/reviewer
- Complex multi-stage → pipeline
- Creative → expert pool
- High-stakes → supervisor

## 4. Files to Create

| File | Purpose |
|------|---------|
| `weebot/application/agents/hyper_agent.py` | HyperAgent orchestrator class |
| `weebot/application/flows/hyper_agent_flow.py` | HyperAgentFlow state machine |
| `weebot/infrastructure/swarm_event_bus.py` | SwarmEventBus implementation |
| `weebot/application/flows/states/hyper_decomposing.py` | Decomposing state |
| `weebot/application/flows/states/hyper_dispatching.py` | Dispatching state |
| `weebot/application/flows/states/hyper_monitoring.py` | Monitoring state |
| `weebot/application/flows/states/hyper_synthesizing.py` | Synthesizing state |
| `tests/unit/test_hyper_agent.py` | HyperAgent tests |
| `tests/integration/test_multi_agent_workflow.py` | End-to-end multi-agent test |

## 5. Files to Modify

| File | Change |
|------|--------|
| `weebot/tools/tool_registry.py` | Add `coder`, `designer`, `reviewer`, `planner_sub` roles |
| `weebot/application/di/__init__.py` | Add `build_hyper_agent_flow()` method |
| `weebot/interfaces/factories.py` | Add `hyper_agent` flow type to `create_flow()` |
| `weebot/application/di/_agent_tools.py` | Add tool wiring for new roles |
| `cli/commands/flow.py` | Add `flow hyper` CLI command |
| `weebot/config/model_refs.py` | Add `MODEL_HYPER_AGENT` constant (recommend Grok 4.3 for planning) |

## 6. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Sub-agent cost explosion | HIGH | Max concurrency cap (default 4), per-agent token budget, cascade to free models for sub-agents |
| Inter-agent message flood | MEDIUM | Topic-based routing, message dedup, max messages per agent |
| Synthesis quality | MEDIUM | Confidence-weighted clustering, human-in-the-loop for conflicting findings |
| Dead sub-agents blocking synthesis | HIGH | Timeout per sub-agent (default 5 min), partial synthesis on timeout |
| Context window overflow | MEDIUM | Each sub-agent gets summarized context, not full history |

## 7. Execution Order

| Phase | Effort | Dependencies | Delivers |
|-------|--------|--------------|----------|
| 2.1-2.2 (HyperAgent + Flow) | 3 days | Phase 1 (done) | Working parallel agent execution |
| 3.1-3.3 (SwarmEventBus) | 1 day | Phase 2 | Inter-agent communication |
| 4.1-4.2 (Recovery) | 1 day | Phase 2 | Resilience |
| 5.1-5.2 (Templates) | 1 day | Phase 2 | Workflow pattern selection |
| 2.3-2.4 (DI + CLI) | 0.5 day | Phase 2 | User-facing entry point |
| Tests | 1 day | Phase 2-5 | Regression safety |

**Total: ~7.5 days.** Can be parallelized: Phase 2 + Phase 3 can be built concurrently.
