---
name: orchestration_guide
description: Orchestration patterns for parallel subagent and swarm usage when building websites and apps. Covers when to parallelize, file ownership partitioning, the constitution pattern, synthesis strategy, and anti-patterns. Triggered when dispatching parallel tasks, building multi-section websites, building multi-layer apps, or orchestrating agent swarms.
metadata:
  emoji: 🎼
  env: []
---

# Orchestration Guide

You are the **orchestrator**. You decide when to parallelize, what boundaries each sub-agent owns, and how to integrate their outputs. Getting this right saves time and prevents corrupted builds.

---

## 1. The Core Decision: Parallelize or Not?

**Parallelize when ALL of the following are true:**
- Tasks are genuinely independent (no shared mutable state, no ordering dependency)
- Each task requires 4–15 LLM calls to complete
- Each task has a single verifiable output (a file, a test result, a structured report)
- All inputs each task needs are available right now

**Do NOT parallelize when ANY of the following is true:**
- Task A's output is Task B's input
- Tasks write to the same files
- Tasks make independent decisions that must be consistent (e.g., both choose a color palette)
- Total task count < 3 (overhead exceeds gain)
- Tasks require clarification mid-flight (sub-agents cannot ask the user)

**Minimum meaningful sub-task:** 4+ LLM calls. If the work takes 1-3 calls (grep, read, one web search, single bash command), do it inline — dispatching a sub-agent costs more than doing it yourself.

---

## 2. Tool Selection Decision Tree

```
Is the task structure known before starting?
  YES → Are there real dependencies between sub-tasks?
          YES → workflow_orchestrator (DAG engine, per-task timeouts)
          NO  → dispatch_parallel_tasks (explicit list, lowest overhead)
  NO  → Is it exploratory research or analysis?
          YES → swarm (GoalAgent auto-decomposes, Synthesizer merges)
          NO  → Re-examine: if you can enumerate the tasks, use dispatch_parallel_tasks

Is the question best answered by multiple LLM perspectives?
  → mixture_of_agents (multi-model ensemble, no tool access)

Does the decision involve strategic tradeoffs worth arguing both sides?
  → debate (optimist + pessimist + pragmatist + reconciler)
```

### When to use each tool

**`dispatch_parallel_tasks`** — your default for parallel work
- Use when: building N independent UI sections, running N independent tests, analyzing N independent codebases
- Set `max_concurrency: 3` for builds (I/O bound), `max_concurrency: 4` for research (CPU bound)
- No per-task timeout — if a hung sub-agent is a risk, use `workflow_orchestrator` instead
- Returns `{results: [{task_id, status, summary}], completed, failed}`

**`swarm`** — for open-ended research
- Use when: competitive analysis, multi-source investigation, problem exploration where you don't know the sub-tasks yet
- GoalAgent produces 3–6 sub-goals; `max_goals: 5` is a safe default
- SynthesizerAgent merges outputs into clusters + synthesis + blind_spots
- Returns `{synthesis, clusters, consensus, dissent, blind_spots}`

**`workflow_orchestrator`** — for dependency chains
- Use when: tasks have real deps (token extraction → component build → page assembly)
- Each task: `{task_id, description, deps: ["prior-task-id"], timeout: 300}`
- Injects sibling outputs automatically — sub-agents can see what completed tasks produced
- Per-task timeout defaults to 300s; set explicitly for long-running builds

**`mixture_of_agents`** — for hard reasoning questions
- Use when: "what is the optimal architecture for X?", "which library should we use?"
- Calls multiple LLMs in parallel, then aggregates. Pure inference, no tool access.
- Not for construction tasks — MoA agents cannot write files or run tests

**`debate`** — for go/no-go decisions and tradeoff analysis
- Use when: "should we use microservices or monolith?", "is this architecture too complex for the requirements?"
- Returns structured `{consensus, dissent, blind_spots, synthesis}`

---

## 3. Website Development Orchestration

### Dependency order (sequential gates)

Nothing can be parallelized past a gate until it is complete:

```
Gate 1: Brand direction + design token extraction
         ↓
Gate 2: tokens.css written (all CSS custom properties)
         ↓
Gate 3: Base components (Button, Typography, Card) — they consume tokens
         ↓  ← PARALLEL phase opens here
[Hero]  [Nav]  [Footer]  [Pricing]  [Testimonials]  [FAQ]  [CTA]
         ↓  ← PARALLEL phase closes here
Gate 4: Assembly (page.tsx imports all sections in visual order)
         ↓
Gate 5: Build verification (npm run build / tsc --noEmit)
         ↓
Gate 6: Screenshot comparison + visual QA
```

### Safe parallel pairs (these share no state)

- Hero section ↔ Footer section
- Pricing section ↔ Testimonials section
- About section ↔ Contact section
- Copy writing ↔ Asset generation
- Accessibility audit ↔ Performance audit

### Unsafe false parallels (these DO share state)

- Nav section ↔ Page layout (sticky behavior, z-index, viewport assumptions)
- Two sections that both modify `globals.css`
- Hero section ↔ "update the color palette" (palette is Hero's input)

### File ownership template for section sub-agents

Every dispatched task description MUST include:

```
OWNERSHIP: You own exclusively:
  - src/components/<SectionName>/
  - src/components/<SectionName>/<SectionName>.tsx
  - src/components/<SectionName>/<SectionName>.css (if needed)

DO NOT modify: globals.css, tokens.css, tsconfig.json, app/layout.tsx,
src/components/index.ts, or any file outside your ownership scope.

INPUTS: Read these before writing any code:
  - Output/<project>/docs/design_tokens.json (use these exact values, no approximations)
  - Output/<project>/docs/sections.json (your section spec)
```

### Freeze list during parallel phase

The orchestrator must NOT let these files be written during the parallel phase:

| File | Why frozen |
|------|-----------|
| `globals.css` | Would affect all sections simultaneously |
| `tokens.css` | Is the input; modifying it mid-build corrupts all |
| `tsconfig.json` | Compiler config affects all agents' type checks |
| `app/layout.tsx` | Root layout; modifying it changes rendering for all |
| `src/components/index.ts` | Barrel export; simultaneous writes lose entries |

Write barrel exports AFTER the parallel phase completes.

### Example dispatch call for website sections

```json
{
  "tasks": [
    {
      "task_id": "build-hero",
      "description": "Build the Hero section as a React/TypeScript component.\nOWNERSHIP: src/components/Hero/ only. Do NOT touch any other file.\nINPUTS: Read Output/<project>/docs/design_tokens.json for exact values.\nOUTPUT: Hero.tsx exporting a default React component + Hero.css if needed.\nREQ: Use exact CSS values from tokens — no approximations. Include hover states."
    },
    {
      "task_id": "build-pricing",
      "description": "Build the PricingSection component.\nOWNERSHIP: src/components/PricingSection/ only.\nINPUTS: Read Output/<project>/docs/design_tokens.json.\nOUTPUT: PricingSection.tsx + PricingSection.css.\nREQ: 3-tier pricing cards. Highlight the recommended tier."
    }
  ],
  "max_concurrency": 3
}
```

---

## 4. App Development Orchestration

### Dependency order (sequential gates)

```
Gate 1: Architecture Decision Record (Output/<project>/docs/architecture.md)
         ↓
Gate 2: Domain model definitions (entities, value objects, port interfaces)
         ↓
Gate 3: Shared interfaces contract (Output/<project>/docs/interfaces.md)
         ↓  ← PARALLEL phase opens here (services across aggregates)
[UserService]  [OrderService]  [ProductService]
         ↓  ← PARALLEL phase closes
Gate 4: Service integration tests (sequential)
         ↓  ← PARALLEL phase opens here (controllers per route group)
[UserRoutes]  [OrderRoutes]  [ProductRoutes]
         ↓  ← PARALLEL phase closes
Gate 5: Integration + E2E tests
         ↓
Gate 6: Build verification
```

### The constitution pattern (required before any parallel app work)

Write `Output/<project>/docs/interfaces.md` (or `.ts`/`.py`) before dispatching:

```markdown
# Interface Contract

## Shared Types
- User: { id: string, email: string, name: string, createdAt: Date }
- Order: { id: string, userId: string, items: OrderItem[], status: OrderStatus }

## Naming Conventions
- Files: kebab-case (user-service.ts)
- Classes: PascalCase (UserService)
- Methods: camelCase verbs (getUser, createOrder)
- Errors: PascalCase + Error suffix (UserNotFoundError)

## Response Envelope
Success: { success: true, data: T }
Error:   { success: false, error: { code: string, message: string } }

## Error Codes
- USER_NOT_FOUND, ORDER_NOT_FOUND, VALIDATION_ERROR, UNAUTHORIZED

## Module Ownership
- agent-1 (UserService): src/services/user-service.ts, src/repositories/user-repo.ts
- agent-2 (OrderService): src/services/order-service.ts, src/repositories/order-repo.ts
- agent-3 (ProductService): src/services/product-service.ts, src/repositories/product-repo.ts
```

Every sub-agent task description must begin: "Read Output/<project>/docs/interfaces.md first and follow every convention exactly."

### Example dispatch call for app service layer

```json
{
  "tasks": [
    {
      "task_id": "build-user-service",
      "description": "Build the UserService layer for the app.\nRead Output/<project>/docs/interfaces.md FIRST — follow all naming, types, and error conventions exactly.\nOWNERSHIP: src/services/user-service.ts, src/repositories/user-repo.ts\nDo NOT touch any other module.\nIMPLEMENT: getUser(id), createUser(dto), updateUser(id, dto), deleteUser(id)\nTESTS: Write tests in tests/unit/user-service.test.ts using pytest/jest.\nCONFIRM: All tests pass before completing."
    }
  ],
  "max_concurrency": 3
}
```

### Layer parallelism safety matrix

| Layer | Parallelizable? | Condition |
|-------|----------------|-----------|
| Domain models | No | Root contract — serialize |
| Port interfaces | No | Must be consistent |
| Services (per aggregate) | Yes | After domain + interfaces frozen |
| Repositories (per aggregate) | Yes | After domain + interfaces frozen |
| Controllers (per route group) | Yes | After services exist |
| Unit tests (per module) | Yes | After implementation exists |
| Integration tests | No | Depends on all components |

---

## 5. Research Orchestration

Research is the highest-ROI use case for parallelism.

### When swarm beats explicit dispatch for research

Use `swarm` when: you don't know how to decompose the research topic, or you want emergent coverage.

Use `dispatch_parallel_tasks` when: you have a fixed list of sources, competitors, or libraries to evaluate.

### High-value parallel research patterns

```
Competitive analysis:
  → One agent per competitor, same evaluation rubric
  → dispatch_parallel_tasks, each task: "Analyze <competitor> on: pricing, UX, tech stack, API quality"

Library evaluation:
  → One agent per candidate library
  → Each answers the same rubric: "Evaluate <library> on: API ergonomics, bundle size, TypeScript support, community health"

Documentation triangulation:
  → Agent 1: Official docs
  → Agent 2: GitHub issues + recent PRs
  → Agent 3: Community forums / Stack Overflow
  → Orchestrator synthesizes: consensus = reliable, divergence = investigate further

Multi-source fact gathering:
  → dispatch_parallel_tasks with explicit sources
  → Orchestrator validates consistency across sources before accepting
```

### Swarm synthesis output structure

After `swarm` completes, the result contains:
- `synthesis`: 3-5 paragraph summary
- `clusters`: grouped themes across sub-agent findings
- `consensus`: what all agents agreed on
- `dissent`: where agents disagreed (high signal — investigate these)
- `blind_spots`: what was NOT covered (check these manually)

Always read `blind_spots` — they identify gaps in the research coverage.

---

## 6. Synthesis After Parallel Work

The integration step is not bookkeeping — it is the hardest reasoning in the pipeline.

### Mandatory post-dispatch checklist

- [ ] Did all sub-agents complete? Check `failed` count in dispatch result
- [ ] Do outputs follow the spec (constitution / design tokens / ownership rules)?
- [ ] Are there naming conflicts? (Two sections defining `.btn`, two services defining `getById`)
- [ ] Are there type/interface mismatches? (Service returns `userId: number`, controller expects `userId: string`)
- [ ] Are there file write conflicts? (Two agents both wrote `index.ts`)
- [ ] Does the whole assemble correctly? (Run build / tsc / pytest after integration)

### When a sub-agent fails

1. Read its error message — do not ignore `failed` entries
2. If the failure is recoverable (missing file, wrong path): fix inline
3. If the failure indicates bad task decomposition: re-examine the task boundary and re-dispatch
4. Never propagate a partial/failed result to the next phase

---

## 7. Anti-patterns Checklist

Before dispatching, verify none of these apply:

- [ ] **False parallelism**: Two tasks where one depends on the other's output
- [ ] **Vague ownership**: Task description doesn't specify which files the agent owns
- [ ] **Shared mutable files**: Two agents may write to the same file
- [ ] **No constitution**: Parallel app-building agents without a shared interface contract
- [ ] **Too small**: Tasks that take 1-3 LLM calls — do inline instead
- [ ] **Trusting blindly**: Proceeding to assembly without validating sub-agent outputs
- [ ] **Nested dispatch**: Sub-agents that themselves dispatch sub-agents at nesting_level ≥ 2
- [ ] **MoA for construction**: Using mixture_of_agents for tasks that need tool access (file writes, bash)
- [ ] **Dispatch for single calls**: Spawning a sub-agent to do one grep or one web_search
- [ ] **Assembly while building**: Letting assembly/integration run while parallel agents are still working
