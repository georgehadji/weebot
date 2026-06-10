# Sub-Agent Decision Framework — Applied to Weebot

> Based on Will's Anthropic Applied AI workshop:
> "Tool, skill, or subagent? Decomposing an agent that outgrew its prompt"

---

## 1. Decision Gate: Tool → Skill → Subagent

The workshop defines three decomposition primitives. Here is the **exact decision gate** wired into weebot's `ExecutingState`:

```
                        ┌─────────────────────┐
                        │  Step description    │
                        └──────────┬──────────┘
                                   │
                        ┌──────────▼──────────┐
                        │ Is it a single       │
                        │ deterministic call?  │
                        │ (search/bash/read)   │
                        └──────┬───────────────┘
                               │
                    ┌──────────┴──────────┐
                    │ YES                 │ NO
                    ▼                     ▼
              ┌──────────┐    ┌──────────────────────┐
              │  TOOL    │    │ Does it need domain   │
              │(BaseTool)│    │ knowledge or a play-  │
              │          │    │ book that fits in a   │
              │ Lowest   │    │ prompt fragment?      │
              │ cost     │    └──────────┬───────────┘
              └──────────┘               │
                              ┌──────────┴──────────┐
                              │ YES                 │ NO
                              ▼                     ▼
                        ┌──────────┐    ┌──────────────────────┐
                        │  SKILL   │    │ Does it need its own │
                        │(SKILL.md)│    │ plan-act loop over   │
                        │          │    │ multiple tool calls? │
                        │ Mid cost │    └──────────┬───────────┘
                        └──────────┘               │
                                        ┌──────────┴──────────┐
                                        │ YES                 │ NO
                                        ▼                     ▼
                                  ┌──────────┐        ┌──────────────┐
                                  │ SUBAGENT │        │ MAIN AGENT   │
                                  │          │        │ handles it   │
                                  │ Highest  │        │ directly     │
                                  │ cost     │        └──────────────┘
                                  └──────────┘
```

### Gate implementation in `ExecutingState`

```python
async def _resolve_execution_strategy(self, step: Step) -> ExecutionStrategy:
    """Apply the Tool→Skill→Subagent decision gate from Anthropic's workshop."""

    # Gate 1: Single deterministic call?
    if self._is_single_tool_call(step.description):
        return ExecutionStrategy.TOOL  # use existing BaseTool directly

    # Gate 2: Domain knowledge / playbook that fits in a prompt?
    skill_matches = await self._skill_retriever.retrieve(step.description, top_k=1)
    if skill_matches and skill_matches[0].score > 0.3:
        return ExecutionStrategy.SKILL  # inject SKILL.md into system prompt

    # Gate 3: Multi-step sub-task needing its own loop?
    if self._needs_own_loop(step.description):
        return ExecutionStrategy.SUBAGENT  # spawn PlanActFlow child

    # Default: main agent handles it
    return ExecutionStrategy.DIRECT
```

---

## 2. System Prompt Rules → Applied

### Rule: Keep system prompts lean (15–50 lines)

**Current weebot:** `executor_system.txt` is 44 lines — already within range. But we inject skills, personality, and persistent memory on top. 

**Fix:** Cap total system prompt at 150 lines. If exceeded, compress non-essential sections.

```python
MAX_SYSTEM_PROMPT_LINES = 150

def build_system_prompt(core_prompt: str, skill_prompt: str, rules_prompt: str) -> str:
    prompt = core_prompt
    if skill_prompt:
        remaining = MAX_SYSTEM_PROMPT_LINES - len(core_prompt.split('\n'))
        skill_lines = skill_prompt.split('\n')
        if len(skill_lines) > remaining:
            skill_prompt = '\n'.join(skill_lines[:remaining]) + '\n[... truncated]'
        prompt += '\n\n' + skill_prompt
    return prompt
```

### Rule: Progressive disclosure via skills — pull context only when needed

**Already implemented:** `BM25SkillRetriever` retrieves skills at step execution time [executor.py:306-318]. The skill content is only injected when `score > 0.15`.

**Enhancement:** Add lazy reference loading per the existing `Skill.get_reference()` method [skill.py:96-118] — references within a skill are loaded on first access, not at skill load time.

### Rule: Avoid context pollution

**Already implemented:** `ConversationCompressor` compresses middle of conversation buffer at 75% context threshold [executor.py:209-228].

**Enhancement:** Apply the same compression to skill prompts — if a skill exceeds 100 lines, summarize the middle section rather than truncating.

---

## 3. Tool Selection Rules → Applied

### Rule: Start with human-like primitives (bash, file system, web search)

**Already implemented:** `ToolCollection` in `Container.build_mediator()` creates `BashTool`, `FileEditorTool`, `PythonExecuteTool` as the three foundational tools [di/__init__.py:152-159].

**Enhancement:** Lock these three as "always available" — they are never gated by capability tiers or role restrictions.

### Rule: Use code execution for data analysis — don't upload CSVs into context

**Already implemented:** `PythonExecuteTool` runs sandboxed subprocess. `ExecutorAgent` system prompt instructs: "For DATA RETRIEVAL, use LIGHTWEIGHT tools FIRST."

**Enhancement:** Add explicit guidance to `executor_system.txt`:
```
<data_analysis_rules>
- When given a CSV, Excel, or JSON file: use python_execute to write a script
  that reads the file locally. Never read the file content into the chat.
- Use pandas for tabular data, matplotlib for charts, numpy for computation.
- Output results as text summary + save charts as PNGs.
</data_analysis_rules>
```

### Rule: Add custom tools only when primitives are insufficient

**Checklist before adding a new tool:**
1. Can this be done with bash + python_execute + file_editor?
2. Can this be done with a skill (prompt-only, no new tool code)?
3. If both are no → add a new `BaseTool` subclass.

**Applied to our `image_gen` tool:** ✅ Passes — bash/python can't generate images. A skill can't either (needs API calls). Custom tool is justified.

### Rule: Use MCP only for shared, multi-agent tools

**Current weebot:** MCP server exposes bash, python, web_search, file_editor [mcp/server.py] — these are the human-like primitives. Correct per the rule — only expose standardized tools via MCP that multiple agents/clients need.

**Guidance:** Do NOT add custom tools (like `image_gen`, `dispatch_agents`) to the MCP server. They belong to specific agents, not the shared tool surface.

---

## 4. Sub-Agent Rules → Applied

### Rule: Sub-agents only for (A) parallelization or (B) a "fresh mind"

**This is the most impactful rule.** It constrains sub-agent use to exactly two scenarios:

#### Scenario A: Parallelization ("throw a lot of Claude at a problem")

**When:** The task has 3+ independent sub-tasks that can run concurrently.

**Weebot implementation:**
```python
def _qualifies_for_parallelization(step: Step) -> bool:
    """Check if a step qualifies for sub-agent parallelization."""
    desc = step.description.lower()

    # Must have 3+ distinct sub-tasks
    sub_tasks = _extract_sub_tasks(step)
    if len(sub_tasks) < 3:
        return False

    # Must be independent (no sequential dependencies)
    if _has_dependencies(sub_tasks):
        return False  # use WorkflowOrchestrator instead

    return True
```

**Tool:** `dispatch_parallel_tasks` (foreman pattern)

**Examples:**
- ✅ "Research pricing for 5 competitors" → 5 parallel web_search sub-agents
- ✅ "Generate hero, logo, icon, and testimonial images" → 4 parallel image_gen sub-agents
- ✅ "Analyze 3 datasets independently" → 3 parallel python_execute sub-agents
- ❌ "Research, then write report, then review" → sequential pipeline, not sub-agents

#### Scenario B: "Fresh Mind" (separate instance without main agent's context)

**When:** The sub-task needs unbiased judgment uncontaminated by the main conversation.

**Weebot implementation:**
```python
def _qualifies_for_fresh_mind(step: Step, session_events: list) -> bool:
    """Check if a step needs a 'fresh mind' sub-agent."""
    desc = step.description.lower()

    # Review/critique tasks
    if any(kw in desc for kw in ("review", "critique", "audit", "verify", "check")):
        # Only if the main agent generated the content being reviewed
        if _agent_generated_content(step, session_events):
            return True

    # Security-sensitive operations where context could bias
    if any(kw in desc for kw in ("security audit", "penetration test", "red team")):
        return True

    return False
```

**Tool:** `dispatch_parallel_tasks` with `fresh_context=True` (new parameter)

**Examples:**
- ✅ "Review the code I just wrote for security vulnerabilities" → fresh sub-agent without implementation bias
- ✅ "Critique the marketing copy for factual accuracy" → fresh sub-agent sees only the copy, not the research
- ❌ "Continue the implementation of feature X" → needs main agent's context, not sub-agent

### Rule: Consolidate where possible (frontier models absorb sub-agent work)

**Guidance:** As models like Grok 4.3, Claude Opus 4.8, and MiniMax M3 improve, tasks that previously required sub-agents should be folded back:

| Task | Previously needed sub-agent? | Now can be done by main agent? | Because... |
|------|------------------------------|-------------------------------|------------|
| Simple research (2-3 sources) | Yes (parallelization) | Yes | Models now handle multi-source synthesis natively |
| Single-file code review | Yes (fresh mind) | Yes | Models can now self-critique effectively |
| Data analysis of small datasets | Yes (python sub-agent) | Yes | Main agent can call python_execute directly |
| **Deep research (10+ sources)** | **Yes** | No — still needs parallelization | |
| **Full codebase security audit** | **Yes** | No — still needs fresh mind | |
| **Multi-file refactor with dependencies** | **Yes** | No — needs DAG orchestration | |

### Rule: Ensure seamless communication between orchestrator and sub-agents

**Already partially implemented:** `SwarmEventBus` with `InterAgentMessage` [inter_agent.py]. Sub-agents publish findings; synthesizer consumes them.

**Gap to fix:**
```python
# Add to DispatchAgentsTool — parent-to-child context injection
async def _spawn_sub_agent(self, task: dict, parent_context: dict):
    agent = await self._factory.spawn_agent(...)
    # Inject ONLY what the sub-agent needs, not the full history
    agent.inject_context({
        "task": task["description"],
        "relevant_facts": self._extract_relevant_facts(task, parent_context),
        "output_format": task.get("output_format", "text"),
    })
    return agent
```

The orchestrator MUST NOT dump its entire conversation history into the sub-agent. Only inject task-specific context.

---

## 5. Testing & Optimization Rules → Applied

### Rule: Hill-climbing with evals

**Implementation plan for weebot:**

```python
class SubAgentEval:
    """Evaluates whether sub-agent usage was justified."""

    def evaluate(self, session: Session) -> EvalResult:
        sub_agent_calls = [e for e in session.events if e.type == "tool" and e.tool_name in SUB_AGENT_TOOLS]

        for call in sub_agent_calls:
            # Was the step parallelizable?
            step = self._find_step(session, call)
            should_parallelize = self._qualifies_for_parallelization(step)

            # Was a sub-agent actually used?
            used_subagent = call.tool_name in ("dispatch_parallel_tasks", "swarm")

            if should_parallelize and not used_subagent:
                self._flag_missed_opportunity(step)  # Should have used sub-agent but didn't
            elif not should_parallelize and used_subagent:
                self._flag_wasteful_subagent(step)    # Used sub-agent unnecessarily

        return self._compile_results()
```

### Rule: Measure deterministic + non-deterministic metrics

| Metric | Type | Current weebot | Gap |
|--------|------|---------------|-----|
| Latency (step duration) | Deterministic | ✅ `flow_step_duration_seconds` (placeholder) | Needs real timing |
| Token usage per sub-agent | Deterministic | ✅ `ExecutorAgent.token_usage` | Not aggregated across sub-agents |
| Cost per workflow | Deterministic | ❌ | Add `WorkflowCostTracker` |
| Sub-agent success rate | Deterministic | ❌ | Add counter to `DispatchAgentsTool` |
| Output quality (LLM-as-judge) | Non-deterministic | ❌ | Add post-synthesis evaluation |
| Personality/tone consistency | Non-deterministic | ❌ | Add `BehavioralLearner` feedback loop |

### Rule: Verifiability over correctness — inefficient paths are failures

**Applied to sub-agents:**
```python
SUBAGENT_EFFICIENCY_THRESHOLDS = {
    "max_tool_calls": 10,       # Sub-agent exceeded this → flag as inefficient
    "max_wall_clock_seconds": 300,  # 5 minutes
    "min_output_tokens": 20,    # Sub-agent produced almost nothing → wasted
}
```

---

## 6. Sub-Agent Auto-Trigger Rules (Concrete)

### Auto-trigger: When PlanningState creates parallel steps

```python
# In PlannerAgent._parse_plan() or PlanningState.execute()
PARALLEL_KEYWORDS = [
    "research.*in parallel",
    "each.*separately",
    "independently.*for each",
    "for each.*separate",
    "both.*and.*simultaneously",
    "multiple.*concurrently",
    "all at once",
]

def _detect_parallel_intent(prompt: str) -> bool:
    return any(re.search(kw, prompt, re.IGNORECASE) for kw in PARALLEL_KEYWORDS)
```

If the prompt expresses parallel intent → PlannerAgent creates a step using `swarm` or `dispatch_parallel_tasks` instead of sequential steps.

### Auto-trigger: When ExecutingState detects parallelizable sub-tasks

```python
# In ExecutingState, before executing a step
if self._qualifies_for_parallelization(step):
    step.description = f"Use dispatch_parallel_tasks to {step.description}"
    # The executor will see "dispatch_parallel_tasks" in the description
    # and call the tool
```

### Never auto-trigger sub-agents for:
- Single-operation tasks (file read, web search, bash command)
- Tasks the main agent can complete in ≤ 3 tool calls
- Tasks that depend on prior step results
- Tasks where context from the main conversation is essential
