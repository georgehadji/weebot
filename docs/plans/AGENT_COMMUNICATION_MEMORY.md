# Agent Communication & Memory Architecture

> Based on weebot's existing infrastructure (`InterAgentMessage`, `SwarmEventBus`,
> `AgentContext`, `WorkingMemory`, `SessionContext`, `PersistentMemoryTool`)
> and Will's Anthropic workshop rules.

---

## 1. Memory Architecture — Four Tiers

```
┌─────────────────────────────────────────────────────────────────┐
│                      MEMORY ARCHITECTURE                        │
├─────────────┬─────────────┬──────────────┬─────────────────────┤
│   TIER 1    │   TIER 2    │   TIER 3     │       TIER 4        │
│  Ephemeral  │   Session   │   Shared     │    Persistent       │
│  (per-step) │ (per-agent) │ (per-swarm)  │  (cross-session)    │
├─────────────┼─────────────┼──────────────┼─────────────────────┤
│ Lives in    │ Lives in    │ Lives in     │ Lives on            │
│ LLM context │ Session.    │ AgentContext │ disk at             │
│ window      │ events[]    │ .shared_data │ ~/.weebot/memory/   │
│             │ + facts{}   │ + bus        │                     │
├─────────────┼─────────────┼──────────────┼─────────────────────┤
│ Duration:   │ Duration:   │ Duration:    │ Duration:            │
│ 1 step      │ 1 agent run │ 1 workflow   │ Forever              │
├─────────────┼─────────────┼──────────────┼─────────────────────┤
│ Capacity:   │ Capacity:   │ Capacity:    │ Capacity:            │
│ ~128K tok   │ 10MB JSON   │ Unlimited    │ Unlimited            │
│             │ (truncated) │ (in-memory)  │ (disk)              │
└─────────────┴─────────────┴──────────────┴─────────────────────┘
```

### Tier 1: Ephemeral Memory (per-step)

**What:** The LLM's context window — conversation buffer, system prompt, current tool results.

**Weebot implementation:** `ExecutorAgent._conversation_buffer` (deque, max 15 turns). Auto-compressed at 75% context threshold via `ConversationCompressor`.

**What goes here:**
- Current step description
- Last 10-15 tool call results
- Compressed summary of older turns
- Injected skill prompts (only for this step)
- System prompt

**What NEVER goes here:**
- Raw dataset contents (use python_execute instead)
- Full prior session history
- Sub-agent raw outputs (summaries only)

### Tier 2: Session Memory (per-agent)

**What:** All events, facts, and state for one agent's lifecycle. Persisted to SQLite.

**Weebot implementation:** `Session.events[]` (list of `AgentEvent` → JSON blob in SQLite `sessions` table), `SessionContext.facts{}` (key-value fact store), `SessionContext.meta_notes[]` (post-task insights).

**Storage:**
| Field | Type | Purpose |
|-------|------|---------|
| `events[]` | JSON blob | Complete event history (truncated at 10MB) |
| `context.facts{}` | Key-value | Discovered facts (capped at 100) |
| `context.meta_notes[]` | List | Post-task learnings (capped at 20) |
| `context.original_task` | String | First substantive prompt |
| `context.detected_language` | String | ISO 639-1 code |

**Per-agent facts API:**
```python
session.set_fact("competitor_pricing", {"Acme": "$99", "Beta": "$149"})
session.get_fact("competitor_pricing")  # → {"Acme": "$99", "Beta": "$149"}
```

### Tier 3: Shared Memory (per-swarm)

**What:** Cross-agent state shared during a multi-agent workflow. Lives in-memory for the duration of the swarm. NOT persisted to disk (by design — it's transient coordination state).

**Weebot implementation:** `AgentContext.shared_data{}` + `SwarmEventBus` + `InterAgentMessage`.

**Three mechanisms for sharing:**

#### 3a. Shared Data (`AgentContext.shared_data`)

A concurrency-safe key-value store shared between all agents in a swarm via `asyncio.Lock`.

```
HyperAgent creates AgentContext
    │
    ├─► Researcher stores: "pricing.results" = {...}
    │       await ctx.store_result("pricing.results", data)
    │
    ├─► Analyst reads: "pricing.results"
    │       data = await ctx.get_result("pricing.results")
    │
    └─► Synthesizer reads all:
            all_data = await ctx.get_all_results()
```

**API:**
```python
# Write (with lock, timeout 10s)
await ctx.store_result("analyst.metrics.accuracy", 0.95)

# Read (with lock, timeout 5s)
accuracy = await ctx.get_result("analyst.metrics.accuracy")

# Read sibling output
sibling_output = await ctx.get_sibling_output("researcher_abc123")

# Read all (shallow copy under lock)
all_results = await ctx.get_all_results()
```

#### 3b. Event Bus (`SwarmEventBus` + `InterAgentMessage`)

Publish/subscribe for real-time findings. Agents publish as they discover; subscribers receive immediately.

```
Researcher discovers Acme pricing
    │
    ▼
bus.publish(InterAgentMessage(
    sender="researcher-1",
    topic="competitor_found",
    payload={"name": "Acme Corp", "price": "$199/mo"},
    confidence=0.9
))
    │
    ├─► Synthesizer subscribes to "competitor_found"
    │       async for msg in bus.subscribe("competitor_found"):
    │           cluster.add(msg.payload)
    │
    └─► Analyst subscribes to "competitor_found"
            async for msg in bus.subscribe("competitor_found"):
                competitor_prices.append(msg.payload)
```

**Topics per swarm type:**

| Swarm Type | Topics Published | Subscribers |
|------------|-----------------|-------------|
| Research | `competitor_found`, `pricing_discovered`, `trend_identified`, `source_found` | Synthesizer, other researchers |
| Code | `module_completed`, `test_result`, `bug_found`, `api_discovered` | Reviewer, other coders |
| Creative | `design_draft`, `copy_draft`, `brand_element` | Synthesizer |
| Audit | `vulnerability_found`, `compliance_issue`, `code_smell` | Lead auditor |

#### 3c. Direct Context Injection (parent → child)

The orchestrator injects a **minimal task-specific context** into each sub-agent. Per Will's workshop: "do NOT dump the entire conversation history."

```python
# What the orchestrator injects into a sub-agent:
sub_agent_context = {
    "task": "Research pricing for Acme Corp",
    "relevant_facts": {  # Extracted from parent's SessionContext
        "industry": "SaaS",
        "competitors": ["Beta.io", "Gamma.com"],
    },
    "output_format": "json",  # Structured output expectation
    "max_tool_calls": 10,      # Budget constraint
}
```

**What is NEVER injected:**
- The full parent conversation history
- Unrelated facts from other sub-tasks
- Parent's tool call logs
- Parent's reasoning chain

### Tier 4: Persistent Memory (cross-session)

**What:** Knowledge that survives across sessions and workflows. File-backed on disk.

**Weebot implementation:** `PersistentMemoryTool` → `FileSystemMemoryAdapter` → `~/.weebot/memory/AGENT.md` + `~/.weebot/memory/USER.md`

**Two files:**

| File | Content | Updated by | Read at |
|------|---------|-----------|---------|
| `AGENT.md` | Accumulated facts, patterns, successful strategies | Agent during any session | Session start (frozen snapshot) |
| `USER.md` | User preferences, workflow habits, profile | Agent during any session | Session start (frozen snapshot) |

**§-delimited format:**
```
§ Research: competitor pricing follows market-leader anchoring pattern
§ Coding: user prefers TypeScript with strict mode and no any types
§ Workflow: user always wants git commits after each feature completion
```

**Snapshot loading:** At session start, `PersistentMemoryTool.load_snapshot()` reads both files and prepends to the system prompt. The snapshot is **frozen for the entire session** (preserves LLM prefix cache). Mid-session writes update disk immediately but don't affect the current session's snapshot.

---

## 2. Communication Patterns — Orchestrator ↔ Sub-Agents

### Pattern 1: Task Dispatch (One-Way)

```
ORCHESTRATOR                      SUB-AGENT
    │                                  │
    │── dispatch(task, context) ──────►│
    │                                  │ run PlanActFlow
    │                                  │ ...
    │                                  │ done
    │◄──────── result ─────────────────│
```

**When:** Simple independent tasks. The sub-agent only needs the task description + minimal context. No ongoing communication needed.

**Weebot:** `DispatchAgentsTool` — `asyncio.gather` collects final `MessageEvent` from each sub-agent's async generator. No mid-execution communication.

### Pattern 2: Streaming Findings (Publish/Subscribe)

```
RESEARCHER-1          RESEARCHER-2          SYNTHESIZER
    │                      │                     │
    │── publish ──────────┼──────────────────►  │
    │   "acme_found"      │                     │ cluster.add()
    │                      │── publish ────────► │
    │                      │   "beta_found"      │ cluster.add()
    │◄── read "beta" ──────┼── publish ────────► │
    │   (cross-reference)  │   "beta_found"      │ merge()
```

**When:** Independent research/analysis tasks where agents benefit from seeing each other's intermediate findings. Per Will's workshop: agents should leverage shared knowledge before the synthesizer runs.

**Weebot:** `SwarmEventBus` with topic-based pub/sub. Each agent publishes `InterAgentMessage` as it discovers findings. Other agents subscribe to relevant topics. The synthesizer subscribes to ALL topics and clusters incrementally.

**Key rule:** Agents should cross-reference sibling findings. If Researcher-1 discovers a competitor at price X, Researcher-2 should check if their competitor matches the same pattern.

### Pattern 3: Producer-Reviewer Loop (Bidirectional)

```
PRODUCER (coder)                REVIEWER (fresh mind)
    │                                  │
    │── submit(code, tests) ──────────►│
    │                                  │ review
    │◄──── critique ───────────────────│
    │ fix + resubmit                   │
    │── submit(v2, tests) ────────────►│
    │                                  │ review
    │◄──── approved ───────────────────│
    │                                  │
    ▼                                  ▼
  FINAL                             DONE
```

**When:** Coding, writing, or design tasks where an independent review improves quality. Per Will's workshop: the reviewer needs a "fresh mind" — uncontaminated by the producer's implementation decisions.

**Weebot:** `DispatchAgentsTool` with `fresh_context=True`. The producer gets full task context including the codebase. The reviewer gets ONLY the output + review criteria — no implementation history.

**Max iterations: 3** (per the `producer_reviewer.yaml` template: `accept_best_on_max_iterations`).

### Pattern 4: Hierarchical Delegation (Tree)

```
HYPERAGENT
    │
    ├──► TEAM LEAD (research)
    │       ├──► Researcher-1 (competitors)
    │       ├──► Researcher-2 (pricing)
    │       └──► Researcher-3 (market trends)
    │
    ├──► TEAM LEAD (code)
    │       ├──► Coder-1 (backend API)
    │       ├──► Coder-2 (frontend components)
    │       └──► Coder-3 (tests)
    │
    └──► SYNTHESIZER
            └── merges team outputs
```

**When:** Very large tasks requiring domain specialization within domains. Max nesting depth: 3 (enforced by `AgentContext.nesting_level`).

**Weebot:** `WorkflowOrchestrator` with `DependencyGraph`. Team leads are themselves sub-agents that can spawn further sub-agents. The hard cap at 3 levels prevents infinite recursion.

### Pattern 5: Steering (Human-in-the-Loop)

```
USER ──────► HYPERAGENT ──────► SUB-AGENTS
   ◄──────── status ◄──────────── progress
   ────────► ">> focus on pricing" ──────► adjusts focus
```

**When:** User wants to redirect mid-execution without canceling the whole workflow.

**Weebot:** `SteeringPort` + `SteeringEvent`. The user sends `>>` messages via CLI. HyperAgent forwards relevant steering to sub-agents via `InterAgentMessage(topic="steering", ...)`.

---

## 3. Memory Lifecycle — Creating, Sharing, Cleaning Up

### Sub-Agent Spawn Sequence

```
1. HyperAgent creates AgentContext (Tier 3 shared memory)
2. GoalAgent decomposes into SwarmSpec
3. For each SubGoal:
   a. Create ephemeral Session (Tier 2) with id="dispatch-{role}-{uuid}"
   b. Inject minimal context (NOT full history):
      - task description
      - relevant facts from parent's SessionContext.facts
      - output format expectation
   c. Spawn PlanActFlow sub-agent
   d. Sub-agent starts with:
      - Clean conversation buffer (Tier 1) — only system prompt + task
      - Injected facts from parent (Tier 2 → Tier 1)
      - Access to shared AgentContext (Tier 3)
      - Persistent memory snapshot (Tier 4, frozen at workflow start)
4. Sub-agents run in parallel with SwarmEventBus (Tier 3 communication)
5. Synthesizer consumes all results + bus messages
6. HyperAgent persists key findings to Tier 4 (PersistentMemoryTool)
7. Ephemeral sessions cleaned up (Tier 2 can be deleted)
```

### Memory Isolation Guarantees

| Memory Tier | Isolated per sub-agent? | Shared across swarm? | Survives workflow? |
|-------------|------------------------|---------------------|-------------------|
| Tier 1 (context window) | ✅ Fully isolated | ❌ | ❌ |
| Tier 2 (session events/facts) | ✅ Each has own Session | ❌ | ✅ in SQLite |
| Tier 3a (shared_data) | ❌ Shared with lock | ✅ All agents | ❌ |
| Tier 3b (SwarmEventBus) | ❌ Pub/sub | ✅ All agents | ❌ |
| Tier 4 (persistent memory) | ❌ Read-only snapshot | ✅ Read-only | ✅ On disk |

### Cleanup

```python
async def cleanup_workflow(hyper_context: AgentContext, sub_sessions: list[Session]):
    # 1. Collect key findings for persistent memory
    key_findings = extract_key_findings(hyper_context.shared_data)
    await persistent_memory.add_entries(key_findings)

    # 2. Delete ephemeral sub-agent sessions (optional — keep for audit)
    for session in sub_sessions:
        await state_repo.delete_session(session.id)

    # 3. Close SwarmEventBus subscriptions
    bus.close_all()

    # 4. Clear shared data (free memory)
    hyper_context.shared_data.clear()
```

---

## 4. What Communication Goes Where — Decision Table

| Communication Need | Mechanism | Memory Tier | Example |
|-------------------|-----------|-------------|---------|
| "Here's the task, go do it" | Direct injection at spawn | Tier 2 → Tier 1 | Orchestrator spawns sub-agent with task description |
| "I found Acme pricing: $199" | `SwarmEventBus.publish()` | Tier 3b | Researcher publishes finding |
| "What did the researcher find about pricing?" | `AgentContext.get_result()` | Tier 3a | Analyst reads researcher's stored result |
| "Please review this code I wrote" | `DispatchAgentsTool` with `fresh_context=True` | Tier 2 (clean session) | Producer sends code to reviewer sub-agent |
| "Critique: line 42 has a race condition" | `SwarmEventBus.publish()` | Tier 3b | Reviewer publishes feedback |
| "Remember that the user prefers TypeScript" | `PersistentMemoryTool.add()` | Tier 4 | Any agent writes to USER.md |
| "What does the user prefer?" | `PersistentMemoryTool.load_snapshot()` | Tier 4 → Tier 1 | Injected at session start |
| "Continue from step 3" | `SessionContext.facts` + `Session.events` | Tier 2 | Resuming a paused agent |
| "User says: focus on pricing instead" | `InterAgentMessage(topic="steering")` | Tier 3b | HyperAgent broadcasts steering |
