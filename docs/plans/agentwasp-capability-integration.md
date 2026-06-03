# Weebot — AgentWasp Capability Integration Plan

> Maps 8 production-tested AgentWasp capabilities to Weebot's Clean Architecture.
> Drafted 2026-06-04. Source: AgentWasp v2.7.2 analysis + weebot feat/sia-integration.

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Compliance](#architecture-compliance)
3. [Capability 1 — Truth-Binding Response Layer](#capability-1--truth-binding-response-layer)
4. [Capability 2 — Knowledge Graph + Temporal World Model](#capability-2--knowledge-graph--temporal-world-model)
5. [Capability 3 — Plan Critic](#capability-3--plan-critic)
6. [Capability 4 — Capability Tiers per Skill](#capability-4--capability-tiers-per-skill)
7. [Capability 5 — Behavioral Learning Loop](#capability-5--behavioral-learning-loop)
8. [Capability 6 — Controlled Self-Improvement](#capability-6--controlled-self-improvement)
9. [Capability 7 — Autonomous Opportunity Engine](#capability-7--autonomous-opportunity-engine)
10. [Capability 8 — Background Job Infrastructure](#capability-8--background-job-infrastructure)
11. [Dependency Graph](#dependency-graph)
12. [Effort & Timeline](#effort--timeline)
13. [Risk Assessment](#risk-assessment)
14. [Appendix — Existing Weebot Primitives Reused](#appendix--existing-weebot-primitives-reused)

---

## Executive Summary

AgentWasp exposes 8 capabilities beyond the current UNIFIED_ENHANCEMENT_ROADMAP. This plan maps each to Weebot's Clean Architecture, reusing existing primitives (CQRS mediator, AgentEvent pipeline, DI container, SkillRegistry, ToolCollection) rather than building them fresh. Four capabilities are high-impact/low-effort (1, 3, 4, 5); four are medium-effort/strategic (2, 6, 7, 8).

**Total:** ~2,400 new lines across 24 files. 0 new external dependencies beyond existing stack.

---

## Architecture Compliance

Every capability follows these rules:

| Rule | How |
|------|-----|
| Domain models first | Pydantic `BaseModel` in `weebot/domain/models/` |
| Ports before adapters | Abstract interface in `weebot/application/ports/` |
| DI container as single composition root | `weebot/application/di.py` |
| CQRS for mutations | Commands through mediator with pipeline behaviors |
| Tools extend `BaseTool` | Registered in `RoleBasedToolRegistry` |
| Immutable state | `model_copy(update={...})` everywhere |
| Events as audit trail | Every action emits `AgentEvent` → persisted to SQLite |

### Layers touched

```
domain/models/        ← TruthBinding, KnowledgeNode, PlanCritique, CapabilityTier,
                        BehavioralRule, SelfImprovementPatch, OpportunityProposal
application/
  ports/              ← TruthBindingPort, KnowledgeGraphPort, PlanCriticPort,
                        CapabilityGatePort, BehavioralLearnerPort
  services/           ← TruthBinder, KnowledgeGraph, PlanCriticService,
                        CapabilityGate, BehavioralLearner, OpportunityEngine
  cqrs/commands/      ← ExecutePlanStepCommand (modified), ApplyPatchCommand
  skills/             ← skill_manifest.json (extended with tiers)
core/                 ← JobScheduler (extended from SchedulingManager)
infrastructure/
  adapters/           ← DeterministicTruthChecks, SQLiteKnowledgeGraph
  persistence/        ← Job definitions, knowledge graphs tables
tools/                ← audit_tool (Enhancement 11), apply_patch tool
config/               ← capability_tiers.yaml, behavioral_rules.yaml
```

---

## Capability 1 — Truth-Binding Response Layer

### What it does

AgentWasp's `decision_layer.py` (26KB) intercepts agent RESPONSES (not tool calls) before they reach the user and runs 5 deterministic checks — NO LLM in the policy path. If any check fails, the response is blocked or rewritten.

### Weebot Implementation

Weebot's existing `PlanActFlow._emit()` is the injection point. Before every `MessageEvent` is yielded to the user, `TruthBinder.bind()` validates it against 5 portable, auditable rules:

**Domain model**

`weebot/domain/models/truth_binding.py` (new)

```python
class TruthCheck(BaseModel):
    """A single deterministic guard applied to an agent response."""
    name: str               # e.g. "url_substitution", "action_announcer"
    description: str
    check_fn: str           # Python expression evaluated in sandbox
    severity: str           # "block" | "warn" | "rewrite"

class TruthBindingResult(BaseModel):
    """Result of running all truth checks on a response."""
    passed: bool
    original_text: str
    bound_text: str         # Potentially rewritten
    violations: list[dict]  # [{check, message, severity}]
```

**Port**

`weebot/application/ports/truth_binding_port.py` (new)

```python
class TruthBindingPort(ABC):
    @abstractmethod
    async def bind(self, response: str, context: dict) -> TruthBindingResult:
        ...
```

**Service**

`weebot/application/services/truth_binder.py` (new)

5 checks, all deterministic (no LLM):

| Check | What it catches | How |
|-------|----------------|-----|
| **URL Substitution** | Links that don't match actual navigation trace | Compares response URLs against `ToolEvent` history |
| **Action Announcer** | LLM claiming it did X when no ToolEvent for X exists | Compares action verbs in response against `ToolEvent.tool_name` set |
| **Response Grounder** | Vague success claims without concrete output | Requires file paths, URLs, or values in success responses |
| **Schedule Honesty** | LLM promising follow-up it can't deliver | Blocks responses containing "I'll check back" without a `schedule` tool call |
| **Prompt-Leak Redaction** | System prompt fragments leaking into user response | Pattern-matches against known prompt fragments (`<identity>`, invariants) |

**Integration point**

Modify `PlanActFlow._emit()` — before publishing `MessageEvent`, if role is `assistant` and target is `user`, run `TruthBinder.bind()`:

```python
async def _emit(self, event):
    if isinstance(event, MessageEvent) and event.role == "assistant":
        if self._truth_binder:
            result = await self._truth_binder.bind(event.message, {
                "session_events": self._session.events,
                "step": self._plan.current_step,
            })
            if not result.passed:
                event = event.model_copy(update={"message": result.bound_text})
    # ... existing emit logic
```

**Files**

| File | Action | Lines |
|------|--------|-------|
| `weebot/domain/models/truth_binding.py` | Create | ~30 |
| `weebot/application/ports/truth_binding_port.py` | Create | ~15 |
| `weebot/application/services/truth_binder.py` | Create | ~100 |
| `weebot/application/flows/plan_act_flow.py` | Modify | ~15 |
| **Total** | | **~160** |

---

## Capability 2 — Knowledge Graph + Temporal World Model

### What it does

AgentWasp stores entities and relationships in 28 PostgreSQL tables with temporal versioning. This enables queries like "what did the agent know about X on date Y" and cross-session entity resolution.

### Weebot Implementation

SQLite-friendly lightweight graph using adjacency lists. Three tables: `kg_nodes` (entities), `kg_edges` (relationships), `kg_snapshots` (temporal versions). All queries are parameterized SQL — no graph database dependency.

**Domain model**

`weebot/domain/models/knowledge_graph.py` (new)

```python
class KnowledgeNode(BaseModel):
    id: str
    label: str              # "competitor", "person", "technology", "file", "fact"
    name: str
    properties: dict = {}   # {price: "$199/mo", url: "...", confidence: 0.8}
    created_at: datetime
    source_session_id: str  # Which session discovered this
    version: int = 1

class KnowledgeEdge(BaseModel):
    source_id: str
    target_id: str
    relation: str           # "competes_with", "uses", "priced_at", "authored_by"
    confidence: float
    evidence: str           # Citation or tool call that established this edge

class KnowledgeSnapshot(BaseModel):
    timestamp: datetime
    node_id: str
    previous_properties: dict   # What changed
    new_properties: dict
```

**Port**

`weebot/application/ports/knowledge_graph_port.py` (new)

```python
class KnowledgeGraphPort(ABC):
    @abstractmethod
    async def upsert_node(self, node: KnowledgeNode) -> KnowledgeNode: ...
    @abstractmethod
    async def add_edge(self, edge: KnowledgeEdge) -> KnowledgeEdge: ...
    @abstractmethod
    async def query(self, label: str, filters: dict) -> list[KnowledgeNode]: ...
    @abstractmethod
    async def get_neighbors(self, node_id: str, depth: int = 1) -> dict: ...
    @abstractmethod
    async def snapshot(self, node_id: str) -> KnowledgeSnapshot: ...
```

**Service + Adapter**

- `weebot/application/services/knowledge_graph.py` — business logic (deduplication, confidence merging, temporal versioning)
- `weebot/infrastructure/persistence/sqlite_knowledge_graph.py` — SQLite adapter with 3 tables, FTS5 on node names

**Integration**

Inserted into `ExecutingState` after each completed step — facts discovered during the step are upserted as nodes with edges to the current task node.

**Files**

| File | Action | Lines |
|------|--------|-------|
| `weebot/domain/models/knowledge_graph.py` | Create | ~45 |
| `weebot/application/ports/knowledge_graph_port.py` | Create | ~25 |
| `weebot/application/services/knowledge_graph.py` | Create | ~80 |
| `weebot/infrastructure/persistence/sqlite_knowledge_graph.py` | Create | ~100 |
| `weebot/application/flows/states/executing.py` | Modify | ~15 |
| `weebot/application/di.py` | Modify | ~8 |
| **Total** | | **~273** |

---

## Capability 3 — Plan Critic

### What it does

AgentWasp's goal orchestrator validates every plan step via an LLM critic BEFORE execution. If the critic finds flaws (wrong tool choice, missing constraints, unrealistic expectations), the plan is revised before a single tool call is made.

### Weebot Implementation

Weebot's `PlanningState` currently produces a plan and immediately transitions to `ExecutingState`. The Plan Critic inserts a new state between them: `CritiquingState`.

**Domain model**

`weebot/domain/models/plan.py` (modify — add)

```python
class PlanCritique(BaseModel):
    """LLM-generated critique of a plan before execution."""
    plan_id: str
    step_scores: dict[str, float]     # step_id → 0.0–1.0 confidence
    flaws: list[str]                   # Specific concerns
    suggestions: list[str]             # Concrete fixes
    overall_confidence: float
    verdict: str                       # "approved" | "revise" | "reject"
```

**Port**

`weebot/application/ports/plan_critic_port.py` (new)

```python
class PlanCriticPort(ABC):
    @abstractmethod
    async def critique(self, plan: Plan, context: dict) -> PlanCritique: ...
```

**Service**

`weebot/application/services/plan_critic.py` (new)

Lightweight, single-LLM-call critic. Uses the cheapest model (Owl Alpha — free tier) to review plans before they reach the executor. The critic prompt is:

```
You are a plan validator. Review this plan and flag:
1. Steps that use the wrong tool for the job
2. Steps with unrealistic scope (too broad for one step)
3. Missing preconditions (file that should exist, URL that should be verified first)
4. Steps that could run in parallel but are sequenced
Respond with a JSON PlanCritique object.
```

**Integration**

New flow state between `PlanningState` and `ExecutingState`:

```
PlanningState → CritiquingState → ExecutingState (if approved)
                                → PlanningState (if revise requested)
```

If `overall_confidence < 0.5`, the plan is sent back to `PlanningState` with the critique as context. If `0.5 ≤ confidence < 0.8`, the plan proceeds but flaws are injected as warnings into the executor's system prompt. If `≥ 0.8`, the plan proceeds normally.

**Files**

| File | Action | Lines |
|------|--------|-------|
| `weebot/domain/models/plan.py` | Modify | ~15 |
| `weebot/application/ports/plan_critic_port.py` | Create | ~15 |
| `weebot/application/services/plan_critic.py` | Create | ~60 |
| `weebot/application/flows/states/critiquing.py` | Create | ~50 |
| `weebot/application/flows/plan_act_flow.py` | Modify | ~10 |
| `weebot/application/di.py` | Modify | ~5 |
| **Total** | | **~155** |

---

## Capability 4 — Capability Tiers per Skill

### What it does

AgentWasp labels every skill with one of 4 tiers: PUBLIC (safe, no restrictions), CONTROLLED (requires user presence), RESTRICTED (requires explicit approval per use), PRIVILEGED (requires operator override). Before execution, an anticipatory simulation previews consequences of privileged operations.

### Weebot Implementation

Weebot's `SkillPackager` already reads `manifest.json`. Extend the manifest schema with `tier` and permission fields. The `CapabilityGate` service checks the tier before `Skill`s are loaded into `ToolCollection`.

**Domain model**

`weebot/domain/models/capability_tier.py` (new)

```python
class CapabilityTier(str, Enum):
    PUBLIC = "public"          # Safe, no restrictions — always loaded
    CONTROLLED = "controlled"  # Requires user presence (interactive mode)
    RESTRICTED = "restricted"  # Requires explicit user approval per usage
    PRIVILEGED = "privileged"  # Requires operator override token
```

**Extended manifest**

```json
{
    "name": "system_administration",
    "version": "1.0.0",
    "tier": "restricted",
    "requires_user_presence": false,
    "requires_approval_per_use": true,
    "anticipatory_simulation": true,
    "prompt_file": "prompt.md"
}
```

**Port**

`weebot/application/ports/capability_gate_port.py` (new)

```python
class CapabilityGatePort(ABC):
    @abstractmethod
    async def check(self, tier: CapabilityTier, context: dict) -> tuple[bool, str]:
        """Return (allowed, reason)."""
    @abstractmethod
    async def simulate(self, skill_name: str) -> SimulationResult: ...
```

**Integration**

In `SkillPackager.load_skill()`, check `CapabilityGate.check(tier)` before registering the skill. If not allowed, the skill is loaded but gated — the tool appears in the registry but execute() returns `ToolResult.error_result("Skill requires {tier} approval")`.

**Files**

| File | Action | Lines |
|------|--------|-------|
| `weebot/domain/models/capability_tier.py` | Create | ~15 |
| `weebot/application/ports/capability_gate_port.py` | Create | ~20 |
| `weebot/application/services/capability_gate.py` | Create | ~60 |
| `weebot/tools/tool_registry.py` | Modify | ~15 |
| `weebot/skills/builtin/*/manifest.json` | Modify (3 files) | ~9 |
| `weebot/config/capability_tiers.yaml` | Create | ~20 |
| **Total** | | **~139** |

---

## Capability 5 — Behavioral Learning Loop

### What it does

AgentWasp automatically extracts persistent rules from user CORRECTIONS. When a user says "don't do X in the future" or corrects an agent action, the `BehavioralLearner` parses the correction, extracts a rule, stores it, and injects it into every future prompt.

### Weebot Implementation

Weebot's `PersistentMemoryTool` stores facts manually. The Behavioral Learner makes this AUTOMATIC: it monitors `WaitForUserEvent` answers and `SteeringEvent` messages for correction patterns, extracts rules via a cheap LLM call (Owl Alpha), and stores them in a new `behavioral_rules` table.

**Domain model**

`weebot/domain/models/behavioral_rule.py` (new)

```python
class BehavioralRule(BaseModel):
    id: str
    rule_text: str          # "Never use advanced_browser for simple text extraction"
    source_session_id: str  # Which session produced this correction
    source_message: str     # The user's exact correction text
    scope: str              # "global" | "per_skill" | "per_tool"
    created_at: datetime
    applied_count: int = 0  # How many times it was injected
    last_applied_at: Optional[datetime] = None
```

**Port**

`weebot/application/ports/behavioral_learner_port.py` (new)

```python
class BehavioralLearnerPort(ABC):
    @abstractmethod
    async def learn_from_correction(self, user_message: str, context: dict) -> Optional[BehavioralRule]:
        ...
    @abstractmethod
    async def get_active_rules(self) -> list[BehavioralRule]: ...
```

**Service**

`weebot/application/services/behavioral_learner.py` (new)

Triggers on:
1. `WaitForUserEvent` answers containing correction keywords ("don't", "never", "instead", "stop", "wrong")
2. `SteeringEvent` messages with `>>` prefix
3. Post-session user feedback stored in session context

Extracts rules via:

```
User said: "{user_message}"
Context: agent was executing step "{step_description}" and had just called "{tool_name}"

Extract a behavioral rule from this correction. The rule should be a one-sentence imperative.
If the correction is not rule-like (just a normal answer), return null.

Rule: ...
```

**Integration**

Inject active rules into `ExecutorAgent` system prompt alongside `SkillRetriever` results and `PersonalityManager` core identity.

**Files**

| File | Action | Lines |
|------|--------|-------|
| `weebot/domain/models/behavioral_rule.py` | Create | ~25 |
| `weebot/application/ports/behavioral_learner_port.py` | Create | ~20 |
| `weebot/application/services/behavioral_learner.py` | Create | ~80 |
| `weebot/application/agents/executor.py` | Modify | ~10 |
| `weebot/application/flows/states/executing.py` | Modify | ~15 |
| `weebot/config/behavioral_rules.yaml` | Create | ~5 |
| **Total** | | **~155** |

---

## Capability 6 — Controlled Self-Improvement

### What it does

AgentWasp's most ambitious feature: the agent READS, PATCHES, and REBUILDS its own source code. Every patch is validated through AST parsing + sandbox execution before being applied. Patches persist across container rebuilds.

### Weebot Implementation

Constrained to **skill prompts only** — weebot's SkillOptFlow already edits skill `.md` files. Extend it to propose edits to:
- Tool contract YAML files (`weebot/config/contracts/`)
- Rule files (`weebot/config/prompts/rules/`)
- Harness config (`weebot/config/harness/`)

AST validation ensures edited YAML is parseable and JSON schemas are valid. Sandbox testing runs the skill with the edit against validation tasks before accepting.

**Domain model**

`weebot/domain/models/self_improvement.py` (new)

```python
class SelfImprovementPatch(BaseModel):
    id: str
    target_file: str        # Relative path from weebot root
    target_type: str        # "skill" | "contract" | "rule" | "harness"
    diff: str               # Unified diff
    validation_score: float
    validation_tasks: list[str]
    applied: bool = False
    reverted: bool = False
    created_at: datetime
```

**Port**

`weebot/application/ports/self_improvement_port.py` (new)

```python
class SelfImprovementPort(ABC):
    @abstractmethod
    async def propose_patch(self, context: dict) -> Optional[SelfImprovementPatch]: ...
    @abstractmethod
    async def validate_patch(self, patch: SelfImprovementPatch) -> float: ...
    @abstractmethod
    async def apply_patch(self, patch: SelfImprovementPatch) -> bool: ...
    @abstractmethod
    async def revert_patch(self, patch: SelfImprovementPatch) -> bool: ...
```

**Files**

| File | Action | Lines |
|------|--------|-------|
| `weebot/domain/models/self_improvement.py` | Create | ~20 |
| `weebot/application/ports/self_improvement_port.py` | Create | ~25 |
| `weebot/application/services/self_improver.py` | Create | ~100 |
| `weebot/application/flows/skill_opt_flow.py` | Modify | ~30 |
| **Total** | | **~175** |

---

## Capability 7 — Autonomous Opportunity Engine

### What it does

AgentWasp's `opportunity_engine.py` (52KB) is a background job that autonomously discovers goals from memory patterns, evaluates their feasibility, and proposes new tasks — without a user prompt. It reads the knowledge graph, finds gaps, ranks opportunities, and surfaces the top candidates.

### Weebot Implementation

A `JobScheduler` extension that runs a single background job every 6 hours. It:

1. Queries the Knowledge Graph for recent nodes and gaps
2. Queries FTS5 event search for recurring user patterns
3. Ranks opportunities by: novelty × confidence × user-interest-alignment
4. Stores proposals in a `pending_opportunities` table
5. Surfaces them to the user on next interactive session start

**Domain model**

`weebot/domain/models/opportunity.py` (new)

```python
class OpportunityProposal(BaseModel):
    id: str
    prompt: str             # "Research competitor X's new pricing model"
    source: str             # "knowledge_gap" | "recurring_pattern" | "user_interest"
    evidence: list[str]     # Citations from KG or FTS5 search
    confidence: float
    estimated_effort: str   # "low" | "medium" | "high"
    created_at: datetime
    presented: bool = False
    accepted: bool = False
```

**Service**

`weebot/application/services/opportunity_engine.py` (new)

**Files**

| File | Action | Lines |
|------|--------|-------|
| `weebot/domain/models/opportunity.py` | Create | ~20 |
| `weebot/application/services/opportunity_engine.py` | Create | ~100 |
| `weebot/scheduling/scheduler.py` | Modify | ~20 |
| `weebot/infrastructure/persistence/sqlite_state_repo.py` | Modify | ~20 |
| **Total** | | **~160** |

---

## Capability 8 — Background Job Infrastructure

### What it does

AgentWasp runs 41 background jobs: memory consolidation, perception, autonomous goals, self-integrity monitor, CPI monitor, behavioral learner, etc. All run as APScheduler jobs with persistent state and catch-up on restart.

### Weebot Implementation

Weebot already has `SchedulingManager` with APScheduler and SQLite persistence. Extend it with:

1. **Job definitions** — `weebot/config/jobs.yaml` declaring all background jobs
2. **Catch-up on restart** — each job records its last successful run; on startup, missed runs are executed in order
3. **Job registry** — allows adding/removing jobs at runtime via DI

Job types to add:

| Job | Schedule | Dependencies |
|-----|----------|-------------|
| `knowledge_graph_consolidation` | Hourly | Knowledge Graph (Capability 2) |
| `opportunity_scan` | Every 6 hours | Knowledge Graph + FTS5 + Opportunity Engine (Capability 7) |
| `behavioral_rule_consolidation` | Hourly | Behavioral Learner (Capability 5) |
| `self_integrity_check` | Daily | Git status, DB integrity, disk space |
| `memory_cleanup` | Weekly | FTS5 event cleanup, old session archival |

**Files**

| File | Action | Lines |
|------|--------|-------|
| `weebot/config/jobs.yaml` | Create | ~50 |
| `weebot/scheduling/scheduler.py` | Modify | ~30 |
| `weebot/application/di.py` | Modify | ~10 |
| **Total** | | **~90** |

---

## Dependency Graph

```
Capability 1 (Truth Binding) ←── independent, can ship immediately
Capability 4 (Capability Tiers) ←── independent, extends existing SkillPackager

Capability 3 (Plan Critic) ←── independent, inserts between Planning + Executing
Capability 2 (Knowledge Graph) ←── independent, new SQLite tables

Capability 5 (Behavioral Learning) ←── depends on: 1 (truth binding for correction detection)
Capability 6 (Self-Improvement) ←── depends on: 4 (capability tiers for safety gating)

Capability 7 (Opportunity Engine) ←── depends on: 2 (knowledge graph) + 8 (job infra)
Capability 8 (Background Jobs) ←── depends on: 2 (consolidation job) + 7 (opportunity scan job)
```

**Recommended build order:** 1 → 4 → 3 → 2 → 5 → 6 → 8 → 7

Capabilities 1, 4, and 3 can be built in parallel (independent). Capability 2 is the foundation for 5, 7, and 8.

---

## Effort & Timeline

```
Week 1:   Capability 1 (Truth Binding) — 160 lines, 0.5 day
          Capability 4 (Capability Tiers) — 139 lines, 0.5 day
          Capability 3 (Plan Critic) — 155 lines, 0.5 day
          [Total: 1.5 days, 454 lines]

Week 2:   Capability 2 (Knowledge Graph) — 273 lines, 1.5 days
          Capability 5 (Behavioral Learning) — 155 lines, 1 day
          [Total: 2.5 days, 428 lines, running: 4 days]

Week 3:   Capability 6 (Self-Improvement) — 175 lines, 1.5 days
          Capability 8 (Background Jobs) — 90 lines, 0.5 day
          [Total: 2 days, 265 lines, running: 6 days]

Week 4:   Capability 7 (Opportunity Engine) — 160 lines, 1.5 days
          Integration testing, documentation — 2 days
          [Total: 3.5 days, running: 9.5 days ≈ 2 weeks]
```

**Total: ~2,400 lines, 24 files, 9.5 person-days over 4 weeks.**

---

## Risk Assessment

| Risk | Capability | Mitigation |
|------|-----------|------------|
| Truth binding false positives — legitimate responses blocked | 1 | Start with "warn" severity for 2 weeks, escalate to "block" after false-positive rate < 1% |
| Knowledge graph grows unbounded — SQLite file size explosion | 2 | Prune nodes older than 90 days with no edges. Cap at 100K nodes |
| Plan critic increases latency | 3 | Use cheapest model (Owl Alpha — free). Timeout at 5s — proceed without critique on timeout |
| Capability tiers too restrictive — agent can't do its job | 4 | All existing skills default to PUBLIC (backward-compatible). Only new skills get tiered |
| Behavioral learner extracts noise — spurious rules | 5 | Require minimum 2 corrections on same topic before rule extraction. User can review/delete rules |
| Self-improvement corrupts YAML | 6 | AST validation before apply. Auto-revert on parse failure. Git-backed rollback |
| Opportunity engine spams user with low-quality proposals | 7 | Max 3 proposals per day. Confidence threshold 0.7. User must explicitly accept |
| Background jobs consume CPU while user is interacting | 8 | CPU threshold: pause jobs when user load > 50%. Resume when idle |

---

## Appendix — Existing Weebot Primitives Reused

| Primitive | Used By Capability |
|-----------|-------------------|
| `PlanActFlow._emit()` | Truth Binding (1) — injection point for response validation |
| `SessionContext.extra` | Behavioral Learning (5) — store extracted rules |
| `SkillPackager.load_skill()` | Capability Tiers (4) — gate skill loading |
| `SkillOptFlow` | Self-Improvement (6) — extend to edit contracts + rules |
| `SchedulingManager` | Background Jobs (8) — extend with job definitions + catch-up |
| `AgentEvent` union | All — every capability emits typed events |
| `ToolCollection.execute()` | All — canonicalizer + contract injection already present |
| `RoleBasedToolRegistry` | Capability Tiers (4) — add tier check to `get_tools_for_role()` |
| `DI Container` | All — single composition root for all new services |
| `CQRS Mediator` | Plan Critic (3), Self-Improvement (6) — commands through pipeline behaviors |
| `SQLiteStateRepository` | Knowledge Graph (2) — shares connection pool |
| `FTS5 search` | Knowledge Graph (2), Opportunity Engine (7) — full-text entity search |
| `BM25SkillRetriever` | Behavioral Learning (5) — retrieve relevant rules |
| `ContractLoader` | Self-Improvement (6) — contracts as editable targets |
| `RuleSelector` | Behavioral Learning (5) — rules injected alongside selected rules |
| `KeywordTaskRouter` | Opportunity Engine (7) — classify auto-generated proposals |

**Zero new external dependencies.** SQLite handles knowledge graph, capability tiers, behavioral rules, and job persistence. The existing APScheduler handles background jobs. All LLM calls use existing `LLMPort` with the 4-tier cascade.
