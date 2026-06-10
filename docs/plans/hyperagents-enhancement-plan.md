# HyperAgents Enhancement Plan for Weebot

**Source:** Zhang et al. (2026) — *HyperAgents: Self-Referential Agents with Metacognitive Self-Modification*
**Date:** 2026-04-07
**Status:** Draft

---

## Executive Summary

The HyperAgents paper demonstrates that self-referential agents — where the *improvement procedure itself* is subject to modification — can achieve open-ended progress across diverse domains (coding, paper review, robotics reward design, Olympiad math grading). This plan proposes 7 concrete enhancements to weebot inspired by the paper, ordered by dependency and risk.

Every enhancement is mapped to a specific weebot architectural layer and respects the Clean Architecture dependency rule (dependencies point inward: Interfaces → Infrastructure → Application → Domain).

---

## Paper-to-Weebot Concept Map

| HyperAgents Concept | Weebot Mapping |
|---|---|
| Hyperagent = task agent + meta agent in one editable program | PlanActFlow state machine + SelfImprover |
| Metacognitive self-modification | SelfImprover editing its own prompt / allowlist |
| DGM archive of stepping stones | SkillVariantArchive → cross-domain reuse |
| Parent selection with novelty bonus | PlanHistory diversity tracking → novel re-planning |
| Staged evaluation (10-task probe → 100-task full) | SkillOptFlow early-filter evaluator |
| Meta agent evolves from tweaks → structured pipelines | Prompt variants as editable, versioned artifacts |
| Cross-domain transfer of improvement strategies | ImprovementStrategy model → planner prompt injection |

---

## Enhancement 1: Meta-Analysis State

**Priority:** 1 · **Effort:** 2-3 days · **Risk:** Low

### Paper Concept

DGM-H's meta agent observes past task performance and modifies the task agent. The improvement loop is closed: every completed task produces a critique that feeds into the next planning cycle.

### Weebot Mapping

[`PlanActFlow`](../weebot/application/flows/plan_act_flow.py) has a 4-state machine: Planning → Executing → Updating → Summarizing → Completed. There is no observation layer that retrospectively critiques the trajectory for future improvement.

### Implementation

**New files:**
- `weebot/application/flows/states/meta_analysis.py` — new `MetaAnalysisState` (extends `FlowState`, `status = AgentStatus.META_ANALYZING`)
- `weebot/application/services/meta_critic.py` — `MetaCritic` service that takes the full session trajectory and produces a structured critique

**Modified files:**
- `weebot/application/flows/plan_act_flow.py` — insert `MetaAnalysisState` after `SummarizingState` in the state transition logic
- `weebot/application/agents/planner.py` — accept `meta_notes` parameter, inject into planning prompt
- `weebot/config/prompts/planner_system.txt` — add `{meta_notes}` template slot
- `weebot/domain/models/session.py` — add `meta_notes: list[str]` to `SessionContext`

**Meta critic prompt structure:**
```
You are a meta-critic. Review the completed task trajectory and produce:
1. What worked well (keep doing this)
2. What failed (avoid this approach)
3. One concrete change to the planning strategy for next time
```

**Architecture compliance:** ✅ Domain model change is backward-compatible (new field with default `[]`); new state extends existing `FlowState` base; new service lives in Application layer with no inward-breaking deps.

**Verification:**
- Unit test: `MetaCritic` produces parseable JSON from a mock trajectory
- Integration test: After running a 3-step task, the next task's plan avoids a previously failed approach
- Check: `SessionContext.meta_notes` is populated after flow completion

---

## Enhancement 2: Staged Evaluation Protocol

**Priority:** 2 · **Effort:** 1-2 days · **Risk:** Low

### Paper Concept

DGM-H uses a staged evaluation: each agent is first tested on a 10-task probe. Only agents with sufficient probe performance advance to full 100-task evaluation. This dramatically reduces compute cost.

### Weebot Mapping

[`SkillOptFlow`](../weebot/application/flows/skill_opt_flow.py) evaluates every variant against the full benchmark with no early filtering.

### Implementation

**New files:**
- `weebot/application/services/staged_evaluator.py` — `StagedEvaluator` class

**Modified files:**
- `weebot/application/flows/skill_opt_flow.py` — wrap evaluation loop with `StagedEvaluator`

**StagedEvaluator API:**
```python
class StagedEvaluator:
    def __init__(self, probe_size: int = 10, threshold: float = 0.3):
        ...

    async def evaluate(
        self,
        agent: BaseTool,
        tasks: list[Task],
    ) -> StagedResult:
        # Phase 1: probe on first probe_size tasks
        probe_score = await self._run_probe(agent, tasks[:self.probe_size])
        if probe_score < self.threshold:
            return StagedResult(score=probe_score, remaining_assumed_zero=True)
        # Phase 2: full evaluation
        full_score = await self._run_full(agent, tasks)
        return StagedResult(score=full_score, remaining_assumed_zero=False)
```

**Architecture compliance:** ✅ Additive service in Application layer; no domain model changes; existing `SkillOptFlow` callers unchanged.

**Verification:**
- Unit test: `StagedEvaluator` returns `remaining_assumed_zero=True` for low-probe agent
- Unit test: `StagedEvaluator` runs full eval for high-probe agent
- Manual: Run SkillOptFlow on a 50-task benchmark, verify only ~30% of agents receive full evaluation

---

## Enhancement 3: Novelty-Driven Exploration in Planner

**Priority:** 3 · **Effort:** 1-2 days · **Risk:** Low

### Paper Concept

DGM-H's parent selection uses a novelty bonus: `h_i = 1 / (1 + n_i)` where `n_i` is the number of children. Agents with fewer descendants get higher selection weight, preventing premature convergence.

### Weebot Mapping

[`PlannerAgent`](../weebot/application/agents/planner.py) generates plans deterministically from the task description. On retry (e.g., after a failed step triggers `UpdatingState`), it often regenerates similar or identical steps. No mechanism exists to say "try a fundamentally different approach."

### Implementation

**New files:**
- `weebot/application/services/plan_novelty.py` — `PlanNoveltyTracker` class

**Modified files:**
- `weebot/application/services/plan_history.py` — add `diversity_score()` method
- `weebot/application/agents/planner.py` — inject diversity constraints into prompt on re-plan

**PlanNoveltyTracker logic:**
```python
class PlanNoveltyTracker:
    def diversity_score(self, history: list[Plan]) -> float:
        """0.0 = all identical, 1.0 = all completely different."""
        if len(history) < 2:
            return 1.0
        step_hashes = set()
        for plan in history:
            for step in plan.steps:
                step_hashes.add(hash(step.description.lower()))
        return len(step_hashes) / sum(len(p.steps) for p in history)

    def avoidance_prompt(self, history: list[Plan]) -> str:
        """Generate a prompt fragment listing approaches to avoid."""
        frequent = self._frequent_approaches(history, min_count=3)
        if not frequent:
            return ""
        lines = ["\n## Approaches to AVOID (tried 3+ times without success):"]
        for desc in frequent:
            lines.append(f"- {desc}")
        return "\n".join(lines)
```

On re-plan, inject the avoidance prompt into the planner's system message using the existing `SPEC_FILE_RULE` injection pattern at [`planner.py:41-50`](../weebot/application/agents/planner.py:41-50).

**Architecture compliance:** ✅ Application-layer service depends only on domain models; prompt-only injection, no structural changes.

**Verification:**
- Unit test: `PlanNoveltyTracker.diversity_score()` returns 1.0 for first plan, < 1.0 for repeated
- Unit test: `avoidance_prompt()` returns empty for < 3 occurrences
- Integration: Re-plan after 4 identical step failures produces a different approach

---

## Enhancement 4: Skill Variant Archive (DGM Archive)

**Priority:** 4 · **Effort:** 3-4 days · **Risk:** Low

### Paper Concept

DGM-H maintains an archive of previously generated agents. Parent selection uses a sigmoid-weighted combination of performance and novelty. The archive serves as stepping stones for future improvement — old variants are reused when new tasks arrive.

### Weebot Mapping

[`SkillOptFlow`](../weebot/application/flows/skill_opt_flow.py) runs optimization epochs but discards intermediate variants. [`SkillCurator`](../weebot/application/services/skill_curator.py) classifies skills as active/stale/archive-candidate but never *reuses* archived variants. [`EvolutionTracker`](../weebot/application/services/evolution_tracker.py) appends narratives but doesn't structure them as searchable stepping stones.

### Implementation

**New files:**
- `weebot/domain/models/skill_variant.py` — `SkillVariant` Pydantic model
- `weebot/infrastructure/persistence/skill_variant_store.py` — SQLite CRUD for variants
- `weebot/application/services/parent_selector.py` — `ParentSelector` with novelty bonus

**Modified files:**
- `weebot/application/flows/skill_opt_flow.py` — insert variants into archive before accept/reject
- `weebot/application/services/skill_curator.py` — query archive for domain-specific starting points

**Domain model:**
```python
class SkillVariant(BaseModel):
    variant_id: str          # UUID
    parent_id: str | None    # null for seed variants
    skill_name: str
    skill_content: str       # full skill body
    content_hash: str        # SHA-256 for dedup
    score: float             # latest evaluation score
    domain: str              # e.g., "coding", "review", "math"
    generation: int          # depth in the family tree
    children_count: int      # how many variants descend from this
    created_at: datetime
    meta_notes: str          # why this variant was created
```

**ParentSelector (matching paper's formula):**
```python
class ParentSelector:
    def select(
        self,
        archive: list[SkillVariant],
        top_k: int = 3,
    ) -> list[SkillVariant]:
        scored = []
        for variant in archive:
            novelty_bonus = 1.0 / (1.0 + variant.children_count)
            composite = variant.score * novelty_bonus
            scored.append((composite, variant))
        scored.sort(reverse=True)
        return [v for _, v in scored[:top_k]]
```

**Architecture compliance:** ✅ New domain model is pure (no deps); new persistence adapter implements a port from Application layer; `ParentSelector` is an Application service depending only on domain models.

**Verification:**
- Unit test: `ParentSelector` favors high-score, low-children variants
- Unit test: Two variants with same score, different children — the one with fewer children wins
- Integration: Run two SkillOptFlow epochs on different domains; variants from domain A are offered as parents for domain B

---

## Enhancement 5: Editable Prompt Variants

**Priority:** 5 · **Effort:** 2-3 days · **Risk:** Medium

### Paper Concept

In DGM-H, the meta agent's prompt *is* part of the editable program. The improvement procedure evolves from superficial prompt tweaks to structured multi-stage evaluation pipelines over the course of a run.

### Weebot Mapping

Weebot's agent prompts live in static files (`planner_system.txt`, `executor_system.txt`). They're loaded at startup via `importlib.resources` or filesystem path and never modified at runtime. [`SelfImprover`](../weebot/application/services/self_improver.py) can propose edits to contracts and skill files but not to the agent prompts themselves.

### Implementation

**New files:**
- `weebot/domain/models/prompt_variant.py` — `PromptVariant` model
- `weebot/application/services/prompt_registry.py` — `PromptRegistry` for versioned prompts

**Modified files:**
- `weebot/application/agents/executor.py` — accept `prompt_variant_id` parameter in `ExecutorAgent`
- `weebot/application/agents/planner.py` — accept `prompt_variant_id` parameter in `PlannerAgent`
- `weebot/application/services/self_improver.py` — add prompt-editing capability to allowlist
- `weebot/config/prompts/` — add `variants/` subdirectory (git-tracked)

**PromptRegistry design:**
```python
class PromptRegistry:
    """Versioned store for agent prompts.

    Prompts are stored as regular text files under config/prompts/variants/
    with UUID filenames. The registry maps variant_id → file path and tracks
    lineage (parent_id) and evaluation scores.
    """

    def get(self, variant_id: str) -> str:
        """Return the prompt text for a variant."""

    def create(
        self,
        parent_id: str,
        content: str,
        source: str,  # "human", "self_improver", "meta_critic"
    ) -> str:
        """Create a new variant, return its ID."""

    def get_active(self, agent_type: str) -> str:
        """Return the currently active variant ID for agent_type."""
```

**Architecture compliance:** ✅ Prompts remain on disk (git-tracked, rollbackable); agents accept variant IDs as optional parameters (backward-compatible); `PromptRegistry` is an Application service.

**Verification:**
- Unit test: `PromptRegistry.create()` returns valid UUID, file written to disk
- Unit test: `ExecutorAgent(prompt_variant_id="...")` loads the specified variant
- Integration: SelfImprover proposes a prompt edit; new variant is created; agent runs with it

---

## Enhancement 6: Cross-Domain Transfer of Improvement Strategies

**Priority:** 6 · **Effort:** 4-5 days · **Risk:** Medium

### Paper Concept

DGM-H transfers improvement strategies across domains. Strategies learned on paper-review and robotics-reward-design tasks transfer to Olympiad-level math grading. The transfer works because the meta-agent's improvement logic is domain-agnostic.

### Weebot Mapping

Weebot has [`bm25_skill_retriever`](../weebot/application/services/bm25_skill_retriever.py) (lexical BM25 search), [`StrategyAdapter`](../weebot/application/services/strategy_adaptation.py) (in-session), and [`task_model_router`](../weebot/application/services/task_model_router.py) (task → model mapping). None of these transfer *improvement strategies* across domains.

### Implementation

**New files:**
- `weebot/domain/models/self_improvement.py` — `ImprovementStrategy` model (add to existing file)
- `weebot/application/services/strategy_transfer.py` — `StrategyTransferService`
- `weebot/infrastructure/persistence/strategy_store.py` — SQLite adapter

**Modified files:**
- `weebot/application/services/evolution_tracker.py` — persist strategy summary after each epoch
- `weebot/application/agents/planner.py` — inject transferred strategies into prompt
- `weebot/application/services/model_selection.py` — adjust model tier based on domain similarity

**Domain model:**
```python
class ImprovementStrategy(BaseModel):
    strategy_id: str
    source_domain: str          # "coding", "review", "robotics", "math"
    target_domain: str | None   # None = domain-agnostic
    meta_agent_prompt_snippet: str  # the improvement instruction
    effectiveness_score: float  # how well it worked (0..1)
    transfer_count: int         # how many times it was reused
    created_at: datetime
```

**Transfer pipeline:**
1. After each `SkillOptFlow` epoch, `EvolutionTracker` extracts the meta-agent's improvement strategy and persists it as an `ImprovementStrategy`
2. When a new domain flow starts, `StrategyTransferService` queries for strategies with `effectiveness_score > 0.7` from different domains
3. The top-3 strategies by `score × (1 + transfer_count)` are injected into the planner prompt as: `"Prior improvement strategies that worked in other domains:\n- [strategy_1]\n- [strategy_2]"`
4. `TaskModelRouter` uses domain similarity to adjust the initial model tier

**Architecture compliance:** ✅ New domain models are pure; `StrategyTransferService` depends on domain models + `StrategyStore` port; persistence adapter is Infrastructure layer.

**Verification:**
- Unit test: `StrategyTransferService` returns top strategies by composite score
- Unit test: Domain A strategies are offered when starting domain B
- Integration: After running coding tasks, math-task planner receives coding-derived strategies

---

## Enhancement 7: Metacognitive Self-Improvement

**Priority:** 7 · **Effort:** 1-2 days · **Risk:** High

### Paper Concept

The key novelty: the meta agent's own improvement strategy is modifiable. DGM-H with self-improving meta agents significantly outperforms the fixed-meta-agent variant. The meta agent evolves from superficial prompt tweaks to structured multi-stage evaluation pipelines.

### Weebot Mapping

[`SelfImprover`](../weebot/application/services/self_improver.py) has a hardcoded allowlist (lines 27-31): `weebot/skills/builtin`, `weebot/config/contracts`, `weebot/config/prompts/rules`, `weebot/config/harness`. It *cannot* modify its own prompt, its own allowed-target list, or the meta-level parameters that govern how it proposes patches. This is exactly the "fixed meta-level" bottleneck discussed in the paper.

### Implementation

**New files:**
- `weebot/application/services/meta_self_improver.py` — `MetaSelfImprover` (wraps `SelfImprover`)
- `weebot/infrastructure/persistence/meta_improvement_log.py` — audit log for meta-edits

**Modified files:**
- `weebot/application/services/self_improver.py` — add `allow_meta_modification` flag + second-tier allowlist
- `weebot/config/feature_flags.py` — add `METACOGNITIVE_IMPROVEMENT_ENABLED` (default: `False`)

**Safety gates:**
```
METACOGNITIVE_IMPROVEMENT_ENABLED = False  # ← DEFAULT: OFF

if METACOGNITIVE_IMPROVEMENT_ENABLED:
    allowlist.append("weebot/application/services/self_improver.py")
    allowlist.append("weebot/application/services/meta_self_improver.py")
```

**Meta review loop:**
```python
class MetaSelfImprover:
    async def review_and_improve(self, patch_result: PatchResult) -> MetaReviewResult:
        """After SelfImprover proposes a patch, review the proposal strategy."""
        if not METACOGNITIVE_IMPROVEMENT_ENABLED:
            return MetaReviewResult(skip_reason="feature flag disabled")

        review_prompt = f"""
        The SelfImprover just proposed this patch:
        File: {patch_result.file_path}
        Change: {patch_result.summary}
        Strategy used: {patch_result.strategy}

        Review the PROPOSAL STRATEGY (not the patch):
        1. Was this the optimal approach?
        2. Should the SelfImprover's prompt be updated?
        3. Propose a concrete edit to the SelfImprover's improvement strategy.
        """

        review = await self._llm.chat(review_prompt)
        # Log review to MetaImprovementLog for audit
        # If review confidence > 0.8, apply the self-improvement
        ...
```

**Architecture compliance:** ✅ Additive wrapper pattern — `MetaSelfImprover` wraps `SelfImprover`, doesn't modify its internals directly. Feature-flag-gated. All meta-edits logged to audit trail.

**Verification:**
- Unit test: With flag disabled, `MetaSelfImprover` returns `skip_reason="feature flag disabled"`
- Unit test: With flag enabled, successful patch triggers meta-review
- Security test: MetaImprovementLog is append-only, no deletions possible

---

## Phased Roadmap

```
Phase 1 (Week 1) — Immediate Value, Low Risk
├── Enhancement 1: Meta-Analysis State     [2-3d]
├── Enhancement 2: Staged Evaluation       [1-2d]
└── Enhancement 3: Novelty-Driven Planning [1-2d]

Phase 2 (Week 2) — Foundation Building
├── Enhancement 4: Skill Variant Archive   [3-4d]
└── Enhancement 5: Editable Prompts        [2-3d]

Phase 3 (Week 3) — High Ceiling, Gated
├── Enhancement 6: Cross-Domain Transfer   [4-5d]
└── Enhancement 7: Metacognitive Self-Imp. [1-2d]  (feature-flag gated)
```

### Dependency Graph

```
Phase 1 (independent, can be parallelized):
  1 ─┬─ independent
  2 ─┤
  3 ─┘

Phase 2:
  4 ─── independent
  5 ─── independent  (but benefits from 4's archive)

Phase 3:
  6 ─── depends on 4 (needs archive)
          depends on 5 (needs prompt injection)
  7 ─── depends on 5 (needs editable prompts)
          depends on 1 (needs meta-analysis)
          feature-flag gated
```

---

## Risk Assessment

| Enhancement | Operational Risk | Rollback Strategy |
|---|---|---|
| 1. Meta-Analysis | Low — new state, existing patterns | Remove state from flow; meta_notes silently ignored if empty |
| 2. Staged Evaluation | Low — additive evaluator | Revert to full evaluation; no data loss |
| 3. Novelty Planning | Low — prompt-only injection | Remove avoidance prompt; planner works as before |
| 4. Skill Archive | Low — new tables, no migration needed | Drop archive tables; SkillOptFlow works as before |
| 5. Editable Prompts | Medium — prompt quality is critical | Revert to base prompt; variants are additive files |
| 6. Cross-Domain Transfer | Medium — prompt injection volume | Remove strategy injection; planner works as before |
| 7. Meta Self-Improvement | **High** — self-modifying code | Feature flag OFF by default; all edits logged; git rollback available |

---

## Architecture Validation

Every enhancement passes the Clean Architecture dependency rule:

| Enhancement | Domain | Application | Infrastructure | Interfaces | Deps Point Inward? |
|---|---|---|---|---|---|
| 1. Meta-Analysis | `SessionContext.meta_notes` | `MetaCritic`, `MetaAnalysisState` | — | — | ✅ |
| 2. Staged Eval | — | `StagedEvaluator` | — | — | ✅ |
| 3. Novelty Planning | — | `PlanNoveltyTracker` | — | — | ✅ |
| 4. Skill Archive | `SkillVariant` | `ParentSelector` | `SkillVariantStore` | — | ✅ |
| 5. Editable Prompts | `PromptVariant` | `PromptRegistry` | — | — | ✅ |
| 6. Cross-Domain | `ImprovementStrategy` | `StrategyTransferService` | `StrategyStore` | — | ✅ |
| 7. Meta Self-Impr. | — | `MetaSelfImprover` | `MetaImprovementLog` | — | ✅ |

---

## References

- Zhang, J., Zhao, B., Yang, W., Foerster, J., Clune, J., Jiang, M., Devlin, S., & Shavrina, T. (2026). *HyperAgents: Self-Referential Agents with Metacognitive Self-Modification*. arXiv:2603.19461v1.
- Zhang et al. (2025b). *Darwin Gödel Machine*. Prior work on open-ended self-improvement in coding.
- Weebot Architecture: `docs/architecture/`, `CLAUDE.md`
- Weebot Clean Architecture: ADRs in `docs/adr/`
