# Designing Multi-Agent Systems → Weebot: Architecture Analysis & Integration Roadmap

**Source:** `victordibia/designing-multiagent-systems` (last pushed 2026-03-12)  
**Target:** Weebot (`E:\Documents\Vibe-Coding\weebot`)  
**Date:** 2026-06-13  
**Depth:** Architecture-level + implementation-level

---

## Executive Summary

`designing-multiagent-systems` is a didactic but production-quality framework (`picoagents`) and a multi-framework comparison course. Its philosophy is **"build from first principles so you understand the seams."** The core library (`picoagents/`) implements every major multi-agent primitive — agents, orchestrators, memory, tools, termination, evaluation, workflows, context compaction, OTEL, and a WebUI — in ~4 000 lines of clean, serializable Python.

Weebot has a more ambitious capability surface (self-improvement, knowledge graph, RAG, CQRS, model cascade, skills marketplace), but is missing several *structural* primitives that picoagents codifies rigorously:

- **Composable termination conditions** (Weebot relies on ad-hoc max-iteration checks)
- **Serializable agent/orchestrator configs** (Weebot lacks a unified `dump_component` / `load_component` round-trip)
- **First-class evaluation harness** that scores individual trajectories with an LLM judge
- **Context compaction** wired into the token loop (Weebot has `MemoryCompactor` but it is not integrated into the tool loop)
- **Structured tool-approval HITL** (Weebot has human-interaction domain service but no `ToolApprovalRequest` protocol)
- **DAG-based typed workflow step system** (Weebot has `WorkflowPlanner` but it is template-driven, not graph-executed)

Top 3 highest-ROI upgrades: **(1) composable termination**, **(2) per-step LLM evaluation in PlanActFlow**, **(3) context compaction wired into the ExecutorAgent loop**.

---

## Phase 1 — Repository Deconstruction

### 1.1 Core Philosophy

The repo title says it plainly: *designing* systems, not just running them. The README positions the book/course around understanding primitives so practitioners can operate any framework. The `picoagents` package is the "build it yourself" reference implementation — intentionally small, fully typed, and serializable.

Key axioms surfaced across every module:
- **Single-responsibility components**: agents don't orchestrate; orchestrators don't execute tools.
- **Structured output everywhere**: every LLM call that makes a decision (agent selection, step evaluation, judge scoring) uses Pydantic-validated structured output, never text parsing.
- **Explicit termination**: running loops always carry a `BaseTermination` instance so they can stop gracefully.
- **Serialization as a first-class concern**: `Component[Config]` base class gives every primitive a `dump_component()` / `load_component()` round-trip.
- **Evaluation is not an afterthought**: `picoagents.eval` is a first-class sub-package with datasets, judges, runners, and middleware.

### 1.2 System Design Principles

| Principle | Where It Appears | File |
|-----------|-----------------|------|
| Structured LLM output for all decisions | `AgentSelection`, `ExecutionPlan`, `StepProgressEvaluation`, `JudgeResponse` | `orchestration/_ai.py`, `orchestration/_plan.py`, `eval/judges/_llm.py` |
| Composable via `\|` and `&` operators | `CompositeTermination.__or__`, `__and__` | `termination/_composite.py` |
| Component serialization contract | `Component[Config]` base | `_component_config.py` |
| Context compaction inside loop | `CompactionStrategy.compact()` called before each LLM call | `compaction.py`, `agents/_agent.py` |
| Token-aware termination | `TokenUsageTermination` | `termination/_token_usage.py` |
| Tool approval as first-class protocol | `ToolApprovalRequest`, `ToolApprovalResponse` in `AgentContext` | `context.py` |
| Framework-agnostic model clients | `BaseChatCompletionClient` + Anthropic/OpenAI/Azure adapters | `llm/_base.py`, `llm/_anthropic.py` |

### 1.3 Agent Interaction Model

The agent core (`agents/_agent.py`) implements a **ReAct loop**:

```
UserMessage → [Memory.get_context()] → LLM call
                    ↓
           ToolCallRequest? → execute tool → ToolMessage → loop
                    ↓ (no tool call)
           final AssistantMessage → Memory.add() → yield AgentResponse
```

Key design choices:
- `max_iterations` guards infinite loops (default 10 per agent).
- Memory is injected at the start of each run, not per-iteration — agents that need per-iteration retrieval must explicitly call `memory.query()` via a tool.
- Tool results are optionally summarized by the LLM (`summarize_tool_result=True`) — disabling this short-circuits after tool execution, useful for streaming pipelines.
- The agent is a `Component[AgentConfig]` so its entire state (name, instructions, model, tools, memory) can be serialized to JSON and rehydrated.

### 1.4 Coordination Patterns

Three patterns are implemented:

**RoundRobin** (`orchestration/_round_robin.py`): strict cycling through agents, each sees full shared conversation. Simple but inflexible.

**AIOrchestrator** (`orchestration/_ai.py`): LLM picks next agent every turn using `AgentSelection` structured output (selected_agent, reasoning, confidence 0-1). Maintains a `selection_history` list for metadata/diversity analysis. Caches agent capability string for performance.

**PlanBasedOrchestrator** (`orchestration/_plan.py`): generates an `ExecutionPlan` (list of `PlanStep`) on first call using structured LLM output, then:
1. Routes each step to the assigned agent
2. Evaluates completion with `StepProgressEvaluation` (LLM call with structured output)
3. On failure: generates `retry_instructions` and re-runs up to `max_step_retries`
4. On max retries: skips and advances

The **HandoffOrchestrator** (`orchestration/_handoff.py`) is a stub (TODO) — agents emit handoff requests and control transfers explicitly.

### 1.5 Memory / Context Management

Three memory tiers:

| Class | Backend | Retrieval | Persistence |
|-------|---------|-----------|-------------|
| `ListMemory` | Python list | Linear scan (text match) | In-process only |
| `FileMemory` | JSON file | Linear scan (text match) | Cross-session (file) |
| `ChromaDBMemory` (`memory/_chromadb.py`) | ChromaDB | Vector similarity | Cross-session (DB) |

All implement `BaseMemory` with `add()`, `query()`, `get_context()`, `clear()`.

Context compaction (`compaction.py`) is a separate concern: `HeadTailCompaction` preserves the first N% (head — original instructions/context) and last M% (tail — recent tool interactions) of message history. It is called **before every LLM call** in the agent loop, replacing the working message list — this is the key design insight that actually reduces cumulative token usage.

### 1.6 Tool Invocation Strategy

- Tools are Python functions decorated with `@tool` (or `@tool(approval_mode="always_require")`).
- `approval_mode` is first-class: before executing a tool in approval mode, the agent emits a `ToolApprovalRequest` into `AgentContext`, yields to the caller, and waits for a `ToolApprovalResponse`.
- Tools can be MCP-backed (`tools/_mcp/`): MCP client discovers tools from an MCP server and wraps them as local `BaseTool` instances.
- Tools have Pydantic input validation and typed return values.
- `_coding_tools.py` and `_research_tools.py` provide reusable batteries.

### 1.7 Evaluation Framework

`picoagents.eval` is a complete evaluation sub-package:

```
EvalRunner
  ├── Dataset (list of Task objects with rubric, eval_criteria)
  ├── Target (wraps Agent or AgentConfig)
  ├── Judge (LLMEvalJudge, ReferenceJudge, CompositeJudge)
  └── RunMiddleware (telemetry, timing)
```

`LLMEvalJudge` uses structured output (`JudgeResponse` with per-criterion `CriterionScore` items, scores 0-10 with reasoning). Supports `parallel_tasks` and `parallel_targets` flags. `EvalResults` aggregates scores across tasks and targets with CSV export and PNG plotting.

`RunTrajectory` records the full message log, tool calls, usage stats, and timing for every task run — this is the evaluation artifact.

### 1.8 Scaling Assumptions

- **Horizontal**: `EvalRunner(parallel_tasks=True, parallel_targets=True)` uses `asyncio.gather` — not distributed.
- **State**: `BaseOrchestrator.shared_messages` is in-process list; no distributed state.
- **Context**: compaction via `HeadTailCompaction` — token budget set by caller.
- **Cost**: no built-in model cascading; caller selects model upfront.
- **Cancellation**: `CancellationToken` propagates through every async call — clean shutdown.
- **Checkpoints**: `workflow/core/_checkpoint.py` serializes workflow execution state.

---

## Phase 2 — Pattern Extraction

| Pattern | Purpose | Benefits | Limitations | Reusability |
|---------|---------|----------|-------------|-------------|
| `Component[Config]` serialization | Full agent/orchestrator round-trip serialization | Load agents from JSON/DB; version them; share configs | Requires all child objects to also be Components | 9 |
| `AgentSelection` structured output | LLM picks next agent with reasoning + confidence | Inspectable decision log; confidence filter | Extra LLM call per orchestration turn | 8 |
| `PlanBasedOrchestrator` with per-step LLM eval | Retry failed steps with LLM-generated feedback | Self-correcting execution; no hard-coded heuristics | 2 LLM calls per step (execute + evaluate) | 9 |
| `CompositeTermination` with `\|` / `&` | Declare when loops stop as boolean combinations | Readable, composable, extensible | Stateful (need `reset()` between runs) | 10 |
| `HeadTailCompaction` | Keep head + recent tail of message history in token budget | Predictable token cost; preserves original instructions | Drops middle of conversation | 8 |
| `ToolApprovalRequest` / `ToolApprovalResponse` | Pause tool execution for human approval | Auditable; reversible; works async | UX overhead; requires caller to handle yield | 9 |
| `LLMEvalJudge` with structured scoring | Multi-criterion trajectory scoring by another LLM | Scalable, criterion-specific, reasoned scores | Expensive (one LLM call per task result) | 9 |
| `RunTrajectory` | Full execution artifact (messages, tools, usage, timing) | Complete audit trail; feeds judge; enables regression | Memory cost for long runs | 8 |
| `CompactionStrategy` protocol | Pluggable context management at the loop level | Swap strategies without changing agent code | Caller must wire it into the loop | 9 |
| `CancellationToken` propagation | Cooperative task cancellation at every await | Clean shutdown; avoids zombie coroutines | Must be passed through entire call chain | 8 |
| DAG `Workflow` with typed `Edge`/`Step` | Build pipelines as explicit graphs | Parallel steps, conditional edges, checkpoints | More setup than sequential chains | 7 |
| `@tool(approval_mode=...)` decorator | Declarative tool risk annotation | Intent is in the function definition | Binary risk levels only | 8 |
| Agent capabilities cache in orchestrators | Avoid re-building capability strings per turn | Latency reduction for large agent pools | Stale if agents change during run | 7 |
| `StepProgressEvaluation` feedback loop | LLM evaluates its own step outcome | Adaptive retry with specific guidance | Two LLM calls per step, hallucination risk | 8 |

---

## Phase 3 — Weebot Gap Analysis

| Capability | Repo Approach | Weebot Current State | Gap | Priority |
|------------|--------------|---------------------|-----|----------|
| Composable termination | `CompositeTermination` with `\|`/`&`; 8 concrete conditions | Ad-hoc `max_iterations` check in `PlanActFlow` + `PlanStuckError` | No formal termination protocol; hard to extend | **P0** |
| Per-step LLM evaluation | `StepProgressEvaluation` inside `PlanBasedOrchestrator.update_shared_state()` | Step failure detected by exception/empty output; no structured eval | Steps can silently produce poor output without triggering replanning | **P0** |
| Context compaction in loop | `CompactionStrategy.compact()` before every LLM call | `MemoryCompactor` service exists but not wired into `ExecutorAgent` tool loop | Token costs grow unbounded during long tool chains | **P0** |
| Component serialization | `Component[Config]` round-trip for every primitive | No universal `dump_component` / `load_component`; agent configs are bespoke | Cannot persist agent configurations as data; no hot reload | **P1** |
| Tool approval / HITL | `ToolApprovalRequest` in `AgentContext`; decorator `approval_mode` | `domain/services/human_interaction.py` has `WaitForUserEvent`; no per-tool decoration | HITL is flow-level pause, not tool-level; no programmatic approval response path | **P1** |
| LLM evaluation judge | `LLMEvalJudge` with per-criterion scoring + `RunTrajectory` | `application/harness/scorer.py` exists; HYPOTHESIS: scores are heuristic not LLM-based | No structured multi-criterion LLM judge | **P1** |
| AI-driven orchestration | `AIOrchestrator` with confidence scores and selection history | Single PlannerAgent → single ExecutorAgent; no dynamic routing at orchestration layer | HYPOTHESIS: no multi-agent dynamic routing at runtime | **P1** |
| Agent capability cache | Cached capability string per orchestration run | `weebot/agents/registry.py` has agent registry | HYPOTHESIS: capability resolution happens per-request, not cached per orchestration | **P2** |
| Selection diversity tracking | `agent_diversity` metric in orchestrator metadata | `behavior_tracker.py` exists | HYPOTHESIS: no per-orchestration diversity tracking | **P2** |
| Workflow DAG execution | `BaseWorkflow` with typed `Edge` objects, parallel branches | `workflow_planner.py` generates sequential task lists from templates | No graph execution engine; plans can't have parallel branches | **P2** |
| ChromaDB / vector memory | `ChromaDBMemory` as `BaseMemory` implementation | `qmd_integration/embeddings.py` + `rag_engine.py` exist | RAG and memory are separate subsystems, not unified under `BaseMemory` | **P2** |
| Token-aware termination | `TokenUsageTermination` (character/4 heuristic) | `token_budget_monitor.py` in services | Not a termination condition; doesn't stop the loop | **P2** |
| OTel distributed tracing | `picoagents/_otel.py` + examples/otel/ | HYPOTHESIS: no OTEL instrumentation | Full spans for agent calls, tool calls, LLM calls missing | **P3** |
| Workflow checkpointing | `workflow/core/_checkpoint.py` serializes execution state | No equivalent | Long workflows can't resume after crash | **P3** |
| CancellationToken propagation | Every async method accepts `CancellationToken` | `asyncio.CancelledError` handling in some flows | No unified cooperative cancellation token | **P3** |

---

## Phase 4 — Optimization Opportunities

### Agent Architecture
- Replace `PlannerAgent` + `ExecutorAgent` two-role model with a `PlanBasedOrchestrator`-style router that can spawn specialized agents per step type (coder, researcher, browser agent, etc.).
- Add `AgentConfig` serialization so agent personas can be stored in SQLite and loaded dynamically.

### Workflow Orchestration
- Replace `WorkflowPlanner`'s template dictionary with a graph-execution engine (`BaseWorkflow` + `Edge`) that supports conditional branching and parallel branches.
- Wire `StepProgressEvaluation` into `PlanActFlow.EXECUTING` → `UPDATING` transition so replanning is driven by structured evidence, not just exceptions.

### Memory Systems
- Unify `MemoryFacade` under a `BaseMemory`-compatible interface so `ListMemory`, `FileMemory`, and `ChromaDBMemory` are interchangeable.
- Wire `HeadTailCompaction` (or a Weebot-specific variant using the existing `context_tokenizer.py`) into `ExecutorAgent.run()` before each LLM call.

### Knowledge Retrieval
- `bm25_skill_retriever.py` is text-only. Add `ChromaDBMemory` as a semantic skill retrieval backend, queryable by embedding similarity.
- Unify skill retrieval and memory retrieval under a single abstract port to avoid two separate RAG pipelines.

### Tool Ecosystem
- Add `@tool(approval_mode="always_require")` to Weebot's bash-tier-3 tools and file-delete operations. Replace the heuristic `bash_guard.py` classification with an LLM-based risk classifier that uses structured output.
- Expose MCP tool discovery (`tools/_mcp/`) as a first-class initialization path: at startup, enumerate all connected MCP servers and register their tools under a unified `ToolRegistry`.

### Planning / Reasoning
- Add `AIOrchestrator` as an optional routing layer above `PlanActFlow`. When a task is classified as multi-domain, the AI orchestrator selects which specialized flow (coding, research, browser) to invoke per step.
- Replace the `PlanCriticService` heuristics with an LLM-based critic that returns structured critique (same pattern as `StepProgressEvaluation`) — critique becomes a CQRS command rather than a service call.

### Human-in-the-Loop
- Upgrade `WaitForUserEvent` to carry a `ToolApprovalRequest` payload so the WebUI can render a structured approval card (tool name, parameters, approve/reject buttons) rather than a generic pause message.
- Add `approval_mode` as a first-class field on tool contract YAML files (`weebot/config/contracts/`) so approval requirements are declarative.

### Evaluation / Observability
- Build `WeebotEvalRunner` wrapping `EvalRunner` logic: wrap each skill with an `AgentEvalTarget`, run against a `Dataset` of golden examples, score with `LLMEvalJudge`.
- Add `RunTrajectory` as the canonical output of every `PlanActFlow` run (currently events are streamed but not persisted as a unified artifact).
- Wire OTEL spans into every `LLMPort.chat()` call and every tool execution.

### Cost Optimization
- Port picoagents' model-client abstraction (`BaseChatCompletionClient`) so Weebot's `ModelCascadeService` becomes an adapter on top of it, inheriting the circuit-breaker pattern without duplicating client code.
- Use `TokenUsageTermination` to enforce hard cost caps per session.

### Security / Governance
- Replace `bash_guard.py` text classification with a `@tool(approval_mode="auto_risk")` decorator that consults a small, fast model (Haiku) to classify risk in structured output before execution.
- Audit trail: every `ToolApprovalRequest` and `ToolApprovalResponse` should be persisted to the `EventStore`.

---

## Phase 5 — Integration Roadmap

| Recommendation | Expected Impact | Complexity | Dependencies | Risk | Sequence |
|----------------|----------------|------------|--------------|------|----------|
| Wire `HeadTailCompaction` into `ExecutorAgent` tool loop | Prevents OOM / token overflow on long tasks | Low (< 1 day) | `context_tokenizer.py` already exists | Low | 1 |
| Add `CompositeTermination` to `PlanActFlow` | Replaces ad-hoc max-iter; enables token/timeout termination | Low (< 1 day) | None | Low | 2 |
| `StepProgressEvaluation` in EXECUTING → UPDATING | Steps that silently fail trigger replanning | Medium (2-3 days) | LLMPort call from within flow | Medium (extra LLM cost) | 3 |
| `ToolApprovalRequest` protocol for DANGEROUS tools | Auditable, reversible tool invocations | Medium (2-3 days) | SSE/WebUI to render approval card | Low-Medium | 4 |
| `LLMEvalJudge` for skill evaluation | Replace heuristic harness scoring with reasoned LLM scores | Medium (3 days) | `LLMPort`, `harness/scorer.py` refactor | Low | 5 |
| `Component[Config]` serialization for agents | Persist/reload agent personas; enable hot config changes | High (1 week) | Touches every agent class | Medium | 6 |
| `AIOrchestrator` as multi-agent router | Dynamic agent selection for multi-domain tasks | High (1 week) | Agent registry, new orchestration layer | Medium | 7 |
| DAG workflow engine replacing template planner | Parallel steps, conditional branches in plans | High (1-2 weeks) | `BaseWorkflow` port from picoagents | Medium | 8 |
| Unified `BaseMemory` interface | One retrieval path for ListMemory, FileMemory, ChromaDB | Medium (3 days) | Refactor `memory_facade.py` | Low | 9 |
| OTEL distributed tracing | Full span visibility across agent/tool calls | Medium (3-5 days) | `picoagents/_otel.py` as reference | Low | 10 |

---

## Phase 6 — Advanced Enhancements

### Multi-Agent Patterns Not in Repo

**Critic-Actor Loop:** a second LLM acts as critic of every agent output before it is accepted into shared state. Weebot has `plan_critic_port.py` and `plan_critic.py` — elevate this to the orchestration level so every step result goes through a critique gate.

**Debate Pattern:** two agents with opposing instructions produce arguments; a judge agent synthesizes. Useful for Weebot's research and source-credibility workflows (`source_credibility_assessment.py`).

**Speculative Execution:** launch two agents on parallel hypotheses, take the first successful result, cancel the other. Requires `CancellationToken`.

### MCP Integrations

Weebot already has `mcp_tool_port.py` and `mcp_toolkit_adapter.py`. Port picoagents' `tools/_mcp/` MCP client pattern to auto-discover and register tools at startup. Add `picoagents._mcp._config` style `MCPServerConfig` YAML entries to `weebot/config/` so teams can declare MCP servers without code changes.

### Graph-Based Memory

The existing `knowledge_graph.py` (port: `knowledge_graph_port.py`) is the right structure. Extend it with:
- Nodes typed as `AgentObservation`, `UserFact`, `ToolOutput`, `PlanStep`
- Edges typed as `caused_by`, `contradicts`, `supports`, `next_step`
- Query API: `graph.query("what did we learn about X in the last 3 steps?")` → LLM-synthesized answer

### Long-Horizon Planning

Add a `PlanHorizonExpander` that takes a `Plan` and uses structured LLM output to identify sub-goals that require multiple sessions. Store sub-goals in `sqlite_summary_repo.py` as serialized `ExecutionPlan` objects. Resume via `plan_history.py` across sessions.

### Autonomous Evaluation Loops

Build `AutoEvalLoop`:
1. After each skill execution, create a `Task` with expected output from the skill's contract YAML.
2. Run `LLMEvalJudge` on the trajectory.
3. If score < threshold, emit a `SelfImprovementPatch` command.
4. `self_improver.py` applies the patch within its allowlist.

This closes the self-improvement loop with measurable quality gates.

### Agent Marketplace / Tool Registry

Weebot already has `templates/marketplace.py`. Extend with:
- Skill metadata includes `eval_dataset_url` pointing to golden examples
- Registry API exposes `GET /skills/{id}/benchmark` → run eval suite, return scores
- Skills above threshold score can be published; below threshold are quarantined

### Self-Improvement Mechanisms

`self_improver.py` already exists with sandbox validation and git-backed rollback. Upgrade with:
- `StepProgressEvaluation` as the signal that triggers improvement (not just user correction)
- Prompt variant A/B testing via `skill_variant_store_port.py` (already ported)
- Improvement candidates ranked by expected impact score from `LLMEvalJudge`

### Multi-Model Routing

Weebot's `model_cascade.py` cascades on failure. Upgrade to **task-type routing**:
- Classify task type at planning time (structured output)
- Route: code tasks → Sonnet 4.6; reasoning tasks → Opus 4.8; simple lookups → Haiku 4.5
- Cost accounting per task type via `cost_ledger.py`

---

## Phase 7 — Decision Analysis: Top 10 Highest-ROI Changes

| Rank | Improvement | Impact | Effort | ROI | Why |
|------|------------|--------|--------|-----|-----|
| 1 | Wire `HeadTailCompaction` into `ExecutorAgent` loop | **High** — prevents context overflow, reduces cost per run | **Low** — 1 day, purely additive | ★★★★★ | `MemoryCompactor` already exists; just needs wiring into the tool loop before every LLM call. No architecture change. |
| 2 | `CompositeTermination` replacing ad-hoc max-iter | **High** — enables token budgets, timeout, custom stop signals | **Low** — 1-2 days | ★★★★★ | Direct port from picoagents. Weebot's `PlanActFlow` has a single `max_iterations` integer today; replacing with a `BaseTermination` instance makes the loop composable. |
| 3 | `StepProgressEvaluation` in EXECUTING → UPDATING | **High** — silently failing steps now surface evidence for replanning | **Medium** — 2-3 days, one extra LLM call per step | ★★★★☆ | Currently replanning is triggered by Python exceptions. Many LLM-generated outputs fail silently (wrong format, incomplete). Structured evaluation fixes this. |
| 4 | `LLMEvalJudge` for harness scoring | **High** — replaces heuristic scorer with explainable, criterion-specific scores | **Medium** — 3 days | ★★★★☆ | `harness/scorer.py` already exists; wrapping with `LLMEvalJudge` gives per-criterion reasoning that feeds back into `self_improver.py`. |
| 5 | `ToolApprovalRequest` for DANGEROUS/BLOCKED tools | **High** — auditable HITL without a full flow pause | **Medium** — 2-3 days | ★★★★☆ | Weebot's bash_guard blocks BLOCKED commands hard; dangerous ones proceed silently. Adding an approval gate closes the gap between the 4-tier risk model and actual human oversight. |
| 6 | Unified `BaseMemory` interface | **Medium** — one API for in-process, file, and vector memory | **Medium** — 3 days | ★★★☆☆ | RAG (`qmd_integration/`) and `memory_facade.py` are separate paths. Unifying them prevents drift and allows swapping ChromaDB vs. ListMemory in tests. |
| 7 | `RunTrajectory` as canonical flow output | **Medium** — full replay of any session; feeds eval judge | **Medium** — 3 days | ★★★☆☆ | Events are streamed and logged but not assembled into a single replayable artifact. Adding `RunTrajectory` enables automated regression testing of flows. |
| 8 | `AIOrchestrator` as top-level multi-agent router | **High** — unlocks true multi-agent parallelism | **High** — 1 week | ★★★☆☆ | Currently all tasks flow through a single PlanAct loop. The AI orchestrator lets specialized sub-agents (coder, browser, researcher) be selected dynamically per step. |
| 9 | OTEL distributed tracing | **Medium** — visibility into exactly where latency/cost is spent | **Medium** — 3-5 days | ★★★☆☆ | `picoagents/_otel.py` is a clean reference. Weebot's `health_checks.py` and `event_logging.py` provide the hooks; adding spans to `LLMPort` and tool execution gives the full picture. |
| 10 | `Component[Config]` serialization | **Medium** — persist agent configs; enable A/B agent testing | **High** — 1 week | ★★☆☆☆ | High value long-term (agent versioning, hot reload) but touches every agent class. Do this after the quick wins (1-5) are stable. |

---

## Prioritized Roadmap

### 30-Day Sprint (Quick Wins — no architectural risk)

1. **Wire `HeadTailCompaction` into `ExecutorAgent`**
   - File: `weebot/application/agents/executor.py` (before the `await llm.chat()` call)
   - Implementation: instantiate `HeadTailCompaction(token_budget=80_000, head_ratio=0.2)` in `PlanActFlowConfig`; call `messages = compaction.compact(messages)` each loop iteration.
   
2. **Replace max-iter check with `CompositeTermination`**
   - New file: `weebot/application/termination/base.py` + `composite.py` + `max_steps.py` + `token_usage.py`
   - `PlanActFlow` receives a `BaseTermination` instance instead of `max_iterations: int`

3. **`LLMEvalJudge` wrapping `harness/scorer.py`**
   - Port `eval/judges/_llm.py` → `weebot/application/harness/llm_judge.py`
   - Replace heuristic scores with structured `JudgeResponse` output

4. **`ToolApprovalRequest` for DANGEROUS tier**
   - Extend `AgentContext` (or create `weebot/application/ports/tool_approval_port.py`)
   - Emit `WaitForUserEvent` with `ToolApprovalRequest` payload; WebUI renders structured approval card

### 90-Day Sprint (Structural Upgrades)

5. **`StepProgressEvaluation` in `PlanActFlow` EXECUTING state**
   - After `ExecutorAgent.run()` returns, call `await self._evaluate_step(step, result)` before deciding COMPLETED vs UPDATING

6. **Unified `BaseMemory` interface**
   - Create `weebot/application/ports/memory_base.py` mirroring picoagents `BaseMemory`
   - Adapt `memory_facade.py`, `qmd_integration/rag_engine.py`, `qmd_integration/embeddings.py` to implement it

7. **`RunTrajectory` as canonical output**
   - `PlanActFlow` assembles `RunTrajectory` at end of SUMMARIZING state
   - Store in `sqlite_summary_repo.py` alongside session summary

8. **OTEL distributed tracing**
   - Wrap `LLMPort.chat()` and every tool `__call__` with OTEL spans
   - Use `picoagents/_otel.py` and `examples/otel/` as exact reference

### 180-Day Sprint (Strategic Redesigns)

9. **`AIOrchestrator` as multi-agent router**
   - New flow: `MultiAgentFlow` with `AIOrchestrator` selecting between `PlanActFlow`, `ChatFlow`, `HyperAgentFlow` per task step

10. **`Component[Config]` serialization for agents**
    - `PlannerAgent`, `ExecutorAgent`, every specialist agent gains `dump_component()` / `load_component()`
    - Agent configs stored in `weebot_sessions.db` and loaded by name

11. **AutoEvalLoop closing self-improvement with quality gates**
    - `LLMEvalJudge` scores every skill run; score below threshold enqueues a `SelfImprovementPatch` command

12. **DAG workflow engine**
    - Port `picoagents/workflow/` as `weebot/application/workflow/` with parallel branch support

---

## Repository Philosophy (One-Paragraph Summary)

`designing-multiagent-systems` treats the agent loop as a *protocol*, not a framework. Every primitive — how an agent loops, how it picks the next agent, how it decides to stop, how it evaluates its own output — is expressed as a composable, serializable, structured-output-driven component. The repository's deepest insight is that **termination and evaluation are as important as reasoning and tool use**, and that wiring them as first-class primitives (not afterthoughts) is what separates prototype agents from production ones. Weebot has outpaced picoagents in breadth (self-improvement, skills marketplace, CQRS, knowledge graph), but picoagents has surpassed Weebot in the *structural fundamentals* that make a multi-agent system debuggable, stoppable, measurable, and resumable.
