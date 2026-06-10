# Multi-Agent Optimization & Generalization Research

> Based on a full survey of weebot's multi-agent infrastructure.
> Every gap is grounded in specific file:line evidence.

---

## 1. Cost Optimization

### 1.1 Current State

- `GoalAgent` uses Tier 1 model (FREE MiniMax M3) for decomposition [goal_agent.py:30]
- `SynthesizerAgent` uses same tier for synthesis — no cost differentiation [synthesizer_agent.py:55]
- `DispatchAgentsTool` spawns sub-agents with **no per-agent cost budget** [dispatch_agents.py:85-120]
- `model_cascade_config.py` has `estimate_cost()` but **nothing calls it** [model_cascade_config.py:173]
- Sub-agents use the executor's 4-tier cascade but **no budget cap is enforced per sub-agent**

### 1.2 Optimization: Budget-Aware Agent Tiers

Introduce a 3-tier agent classification based on role complexity:

| Tier | Roles | Model Pool | Max Cost/Session |
|------|-------|-----------|------------------|
| **Budget** | `planner_sub`, `reviewer` | FREE only (MiniMax M3, Riverflow Free) | $0 |
| **Standard** | `researcher`, `analyst`, `coder`, `documentation` | FREE → Budget (≤$0.01/1K tok) | $0.02 |
| **Premium** | `designer`, `automation` | Standard → Premium (≤$0.03/1K tok) | $0.05 |

**Implementation:**
```python
ROLE_COST_TIERS = {
    "researcher": "standard",     # web search costs, but LLM is budget
    "analyst": "standard",        # compute-heavy, needs reliability
    "coder": "standard",          # needs quality for code correctness
    "designer": "premium",        # image gen costs money
    "reviewer": "budget",         # can use free models
    "planner_sub": "budget",      # lightweight planning
    "automation": "standard",     # reliability matters
}
```

Add to `RoleBasedToolRegistry` and enforce in `DispatchAgentsTool`.

### 1.3 Optimization: Free-First Sub-Agent Cascade

Sub-agents should try free models first, only escalating to paid on failure:

```python
SUB_AGENT_CASCADE = [
    "minimax/minimax-m3",           # FREE, 1M context
    "sourceful/riverflow-v2.5-pro:free",  # FREE (images only)
    "qwen/qwen3.7-max",             # paid, coding-strong
    "deepseek/deepseek-v4-pro",     # paid, reasoning
]
```

Already partially implemented in `ExecutorAgent._call_with_cascade()` — needs to be configurable per role.

### 1.4 Optimization: Cost Tracking Per Workflow

Add cumulative cost tracking to `HyperAgent`:

```python
class WorkflowCostTracker:
    total_cost: float = 0.0
    per_agent_costs: dict[str, float] = {}
    cost_limit: float = 0.50  # hard cap per workflow

    def can_afford(self, role: str, estimated_cost: float) -> bool:
        return self.total_cost + estimated_cost <= self.cost_limit
```

Wire into `DispatchAgentsTool` — refuse to spawn agents that would exceed budget.

---

## 2. Speed Optimization

### 2.1 Current State

- `DispatchAgentsTool` uses static `Semaphore(max_concurrency=4)` [dispatch_agents.py:95]
- `SwarmTool` pipeline is fully synchronous: decompose → dispatch → wait-all → synthesize
- No partial results streaming — caller waits for ALL agents before seeing anything

### 2.2 Optimization: Adaptive Concurrency

Tune concurrency based on task count and available models:

```python
def adaptive_concurrency(num_tasks: int, free_models_available: int) -> int:
    if num_tasks <= 2:
        return num_tasks
    if free_models_available >= 4:
        return min(num_tasks, 8)  # free models → parallelize aggressively
    return min(num_tasks, 4)      # paid models → conservative
```

### 2.3 Optimization: Speculative Execution

For producer/reviewer patterns, run the reviewer **in parallel** with the producer on a different model:

```python
# Instead of: Producer → wait → Reviewer
# Do:        Producer ─┬─ wait ─► Merge
#            Reviewer ─┘  (starts immediately on a different model)
```

The reviewer gets the same prompt and can start critiquing while the producer is still coding. On producer completion, the reviewer already has context.

### 2.4 Optimization: Early Termination

Stop the swarm when enough results are in:

```python
async def dispatch_with_early_termination(goals, min_results=2):
    results = []
    async for result in dispatch_streaming(goals):
        results.append(result)
        if len(results) >= min_results and _sufficient_coverage(results):
            cancel_remaining()  # don't waste tokens
            break
    return results
```

### 2.5 Optimization: Streaming Synthesis

Synthesizer should emit partial results as agents complete, not wait for all:

```python
async def synthesize_streaming(goals, agent_stream):
    buffer = []
    async for agent_result in agent_stream:
        buffer.append(agent_result)
        if len(buffer) >= 2 or agent_result.is_critical:
            partial = await synthesize_partial(buffer)
            yield partial  # caller sees incremental output
    yield await synthesize_final(buffer)  # final merged result
```

---

## 3. Quality Optimization

### 3.1 Current State

- `SynthesizerAgent` has `"vote"` strategy in `SwarmSpec` but **it's not implemented** [synthesizer_agent.py:80: `# TODO: implement voting`]
- No verification loop — synthesis accepts LLM output without validation
- No confidence scoring on synthesized results

### 3.2 Optimization: Multi-Model Voting

For high-stakes sub-goals, run the SAME task on 2-3 different models and vote:

```python
async def voted_dispatch(goal: SubGoal, models: list[str] = None):
    models = models or ["minimax/minimax-m3", "qwen/qwen3.7-max", "deepseek/deepseek-v4-pro"]
    results = await asyncio.gather(*[
        run_agent(goal, model=m) for m in models
    ])
    return majority_vote(results)  # 2/3 agreement → accept
```

Add a `voting: bool` flag to `SubGoal` — only used for high-stakes goals (security review, financial analysis, legal).

### 3.3 Optimization: Producer-Reviewer Feedback Loop

Already templated in `producer_reviewer.yaml` but not executed at runtime. Add:

```python
async def producer_reviewer_loop(goal, max_iterations=3):
    producer = spawn_agent(role="coder")
    reviewer = spawn_agent(role="reviewer")

    for i in range(max_iterations):
        output = await producer.execute(goal.prompt)
        review = await reviewer.review(output)
        if review.approved:
            return output
        producer.add_feedback(review.critique)  # refine on next iteration
    return output  # best effort after max iterations
```

### 3.4 Optimization: Factual Grounding

Before synthesizing, cross-check claims against web search:

```python
async def ground_claims(synthesis: str) -> str:
    claims = extract_claims(synthesis)  # "X costs $99/mo" → fact check
    for claim in claims:
        evidence = await web_search(claim.text)
        if evidence.contradicts(claim):
            claim.flag("UNVERIFIED")
    return annotate(synthesis, claims)
```

Integrate with existing `ChainOfVerification` service [weebot/application/services/chain_of_verification.py].

---

## 4. Generalization — Making It Work for Any Job

### 4.1 Current State

- `task_model_router.py` is **keyword-only** — fragile, doesn't learn [task_model_router.py:12-60]
- Team pattern templates are **definitions only** — no runtime engine executes them
- `GoalAgent` decomposition prompt is generic — no domain-specific decomposition strategies
- No template auto-selection based on task type

### 4.2 Optimization: Learned Task Classification

Replace keyword routing with embedding-based classification:

```python
class LearnedTaskRouter:
    def __init__(self):
        self._embeddings = load_pretrained()  # or use LLM-as-classifier

    async def classify(self, prompt: str) -> TaskRoute:
        # Use a cheap LLM (MiniMax M3 FREE) to classify in one shot:
        # "Is this: coding | research | analysis | creative | automation | mixed?"
        response = await llm.classify(prompt, categories=TASK_CATEGORIES)
        return TaskRoute(
            category=response.category,
            complexity=response.complexity,
            suggested_pattern=response.pattern,  # fan_out | pipeline | supervisor | single_agent
        )
```

### 4.3 Optimization: Dynamic Template Selection

Use the classified task type to auto-select a team pattern:

| Task Type | Pattern | Why |
|-----------|---------|-----|
| Research / fact-finding | `fan_out_fan_in` | Independent sources → merge |
| Coding / bug-fix | `producer_reviewer` | Code → review → fix loop |
| Data analysis | `pipeline` | Extract → clean → analyze → visualize |
| Creative / design | `expert_pool` | Multiple designs → user picks |
| Security audit | `supervisor` | Central review of all findings |
| Mixed (research + code) | `hierarchical_delegation` | Research team → code team → merge |
| Simple Q&A / single-task | `single_agent` (no swarm) | Overhead not worth it |

### 4.4 Optimization: Domain-Specific Decomposition Prompts

Give `GoalAgent` domain-tuned decomposition instructions:

```python
DECOMPOSITION_PROMPTS = {
    "coding": "Break this coding task into: (1) architecture design, (2) implementation, (3) testing, (4) documentation. Assign coder, reviewer, tester roles.",
    "research": "Break this into parallel research streams: competitive analysis, technical deep-dive, market trends. Assign researcher roles with specific search queries.",
    "analysis": "Break into: data extraction, cleaning, statistical analysis, visualization, interpretation. Pipeline them.",
    "creative": "Generate 3-5 independent creative directions, each by a different designer agent. Review and merge the best elements.",
    "general": None,  # use default decomposition
}
```

### 4.5 Optimization: Self-Configuring Workflow

The HyperAgent should auto-configure based on task analysis:

```python
async def auto_configure(self, prompt: str) -> WorkflowConfig:
    # Step 1: Classify the task
    route = await self._task_router.classify(prompt)

    # Step 2: Select pattern
    pattern = TEMPLATE_MAP[route.category]

    # Step 3: Estimate complexity → set budget
    if route.complexity == "simple":
        config = WorkflowConfig(max_agents=2, cost_limit=0.02, free_only=True)
    elif route.complexity == "complex":
        config = WorkflowConfig(max_agents=6, cost_limit=0.50, allow_premium=True)
    else:
        config = WorkflowConfig(max_agents=4, cost_limit=0.15)

    # Step 4: Select decomposition prompt
    config.decomp_prompt = DECOMPOSITION_PROMPTS.get(route.category)

    return config
```

---

## 5. Priority Implementation Roadmap

| # | Optimization | Impact | Effort | Dependencies |
|---|-------------|--------|--------|--------------|
| 1 | **Free-first sub-agent cascade** | Cuts sub-agent cost 60-80% | 0.5 day | None |
| 2 | **Role-based cost tiers** | Predictable per-workflow cost | 0.5 day | None |
| 3 | **Dynamic template selection** | Works for any job type | 1 day | #1, #2 |
| 4 | **Adaptive concurrency** | 2-3x speedup on free models | 0.5 day | None |
| 5 | **Streaming synthesis** | User sees results 3-5x faster | 1 day | None |
| 6 | **Multi-model voting** | Quality improvement for critical tasks | 1 day | None |
| 7 | **Producer-reviewer loop** | Code quality improvement | 1 day | #6 |
| 8 | **Learned task classification** | Reliable auto-routing | 1 day | #3 |
| 9 | **Cost tracking per workflow** | Budget enforcement | 0.5 day | #2 |
| 10 | **Domain-specific decompositions** | Better sub-goal quality | 0.5 day | #3 |

**Total: ~7.5 days for all optimizations** (can be parallelized: #1-4 are independent).

---

## 6. Quick Wins (Do First)

### Win 1: Free-First Sub-Agent Cascade (0.5 day)

Change `DispatchAgentsTool` to pass a `model_cascade` parameter that starts with free models:

```python
# In dispatch_agents.py
SUB_AGENT_MODEL_CASCADE = [
    "minimax/minimax-m3",     # FREE
    "qwen/qwen3.7-max",       # paid fallback
]
```

### Win 2: Adaptive Concurrency (0.5 day)

Replace static `Semaphore(4)` with a dynamic function:

```python
max_parallel = min(len(goals), 8 if all_free_models else 4)
semaphore = asyncio.Semaphore(max_parallel)
```

### Win 3: Role-Based Model Selection (0.5 day)

Map roles to model preferences in `RoleBasedToolRegistry`:

```python
ROLE_MODEL_PREFERENCES = {
    "coder": ["qwen/qwen3.7-max", "minimax/minimax-m3"],
    "researcher": ["minimax/minimax-m3"],
    "reviewer": ["minimax/minimax-m3"],
    "designer": ["recraft/recraft-v4.1-pro-vector"],
}
```

These three changes alone reduce sub-agent cost by ~70% while improving speed 2-3x.
