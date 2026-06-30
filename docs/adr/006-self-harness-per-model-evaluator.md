# ADR-006: Self-Harness, Per-Model Harness, and Evaluator Co-Evolution

**Status:** Accepted  
**Date:** 2026-06-30  
**Deciders:** Architecture team

## Context

The architecture decisions documented in ADR-001 (Clean Hexagonal Architecture), ADR-002 (CQRS), ADR-003 (SQLite primary store), ADR-004 (import-linter enforcement), and ADR-005 (multi-model cascade) cover the foundational structure. The high-level project overview is in `REASONIX.md`.

Three significant architectural patterns have emerged during Phases 3–7 that are not covered by previous ADRs:

1. **Self-Harness** — the agent automatically evolves its own behavioural instructions by mining failure patterns from past trajectories.
2. **Per-model harness** — different LLM models in the cascade receive model-specific instruction overlays rather than a single shared harness.
3. **Evaluator co-evolution** — the evaluation harness that scores agent outputs evolves alongside the agent itself, preventing the "fixed yardstick" problem.

This ADR documents these decisions and why they were chosen.

---

## Decision 1: Self-Harness (Autonomous Harness Evolution)

### Problem

Agent harnesses (behavioural instructions, runtime policies, subagent definitions) were hand-tuned. Each failure pattern discovered in production required a manual edit to the YAML configuration. This created a slow feedback loop: failure observed → developer edits harness → deploy → wait for next failure to validate.

### Decision

Adopt a **Self-Harness loop** that autonomously proposes and validates harness edits by mining failure patterns from the trajectory repository. The loop follows a Rollout → Mine → Propose → Apply → Validate → Accept/Reject cycle:

- **Rollout**: Run the agent on held-in evaluation tasks under the current harness config.
- **Mine**: Query the trajectory repository (`TrajectoryRepositoryPort`) for failure clusters grouped by terminal cause, agent behaviour, and mechanism. Each cluster has a support count and actionability score.
- **Propose**: An LLM call generates candidate edits targeting specific harness surfaces (instruction text, middleware rules, subagent definitions, tool policies). The proposal prompt includes the current harness state and ranked failure patterns.
- **Apply**: Edit the harness config in-memory via `HarnessOptimizationTarget.apply_edits()`.
- **Validate**: The `RegressionGate` runs the candidate harness against held-in/held-out task sets. Accept if `Δ_in ≥ 0` (no regression on held-in) and `Δ_ho ≥ 0` (generalisable).
- **Promote**: Accepted edits are saved as a new versioned YAML file. Gated surfaces (runtime_control, middleware, subagents) require human approval via `WaitForUserEvent` before promotion.

### Implementation

- **`HarnessOptFlow`** in `weebot/application/flows/harness_opt_flow.py` — the optimization loop orchestrator.
- **`HarnessOptimizationTarget`** in `weebot/application/services/harness_optimization_target.py` — load/edit/save harness YAML files with version bumping.
- **`RegressionGate`** in `weebot/application/services/regression_gate.py` — holds evaluation score baseline vs candidate.
- **`HarnessSafetyGate`** in `weebot/application/services/harness_safety_gate.py` — classifies edit surfaces as autonomous vs gated (human-approval required).
- **`TrajectoryRepository`** in `weebot/infrastructure/persistence/trajectory_repo.py` — stores failure signatures and provides clustering queries.
- **Scheduler** in `weebot/config/jobs.yaml` — a weekly cron job (`self_harness_weekly`) triggers evolution automatically.

### Consequences

**Positive:**
- Failure-to-fix cycle reduced from days to hours (autonomous).
- Harness continuously improves without developer intervention.
- Each evolved version is a committed YAML file — auditable, revertible.
- The same mechanism works for instruction text and structural policies.

**Negative:**
- Regression gate quality depends on the held-in task suite. A weak suite produces false-positive promotions.
- Proposals are LLM-generated, so quality varies with the proposal model.
- Autonomous evolution can drift the harness away from developer intent over many iterations.

**Compliance:** `HarnessSafetyGate.check()` is enforced in the flow before any save. Gated surfaces (runtime control knobs, middleware additions, subagent definitions) always yield `WaitForUserEvent`. Architecture fitness tests verify the loop integration.

---

## Decision 2: Per-Model Harness Overlays

### Problem

The model cascade (ADR-005) routes tasks through different LLM models with different strengths. A single shared harness config applied uniformly across all models was suboptimal — fine-tuning instructions for deepseek on code-heavy tasks was counterproductive when the same harness ran on a chat-focused model.

The Self-Harness paper's finding that "harness effectiveness is model-specific" motivated a design that allows per-model optimization without duplicating the entire harness.

### Decision

Adopt a **base + overlay** harness architecture:

1. **Base config** (`weebot/config/harness/v0.2.0.yaml`) — shared harness covering structural layers (canonicalizer, skill_retrieval, trajectory) and default behavioural instructions.
2. **Overlay files** (`weebot/config/harness/overlays/*.yaml`) — model-specific instruction overrides keyed by glob patterns matching model IDs (e.g. `gpt-4o.yaml`, `deepseek*.yaml`).
3. **Per-model harness YAML files** (`weebot/config/harness/models/*.yaml`) — full standalone harness configs for models with heavily customized behaviour.

The `ModelAwareHarnessResolver` resolves at runtime: for each executor step, the active model's overlay (if any) is merged into the base config via `model_copy(update={...})`. Model-cascade fallbacks get appropriate instructions automatically.

### Implementation

- **`ModelAwareHarnessResolver`** in `weebot/application/services/model_aware_harness_resolver.py` — loads overlays, resolves by fnmatch pattern, merges only the `instructions` section.
- **`HarnessConfig`** in `weebot/config/harness/schema.py` — the top-level config model.
- **Model-specific YAMLs** in `weebot/config/harness/models/` — one per cascade tier (e.g., `deepseek_deepseek-v4-flash.yaml`, `z-ai_glm-5.2.yaml`).
- **Resolver integration** in `PlanActFlow` — resolved instruction block is injected into the executor's system prompt per-step.

### Consequences

**Positive:**
- Model-specific tuning without config duplication (overlays are tiny delta files).
- Self-Harness can evolve overlays independently for different models.
- New models just need a new overlay YAML — no code changes.
- Cascade fallback works correctly: when a task drops from tier-1 to tier-2, the tier-2 overlay applies automatically.

**Negative:**
- Overlay resolution adds a runtime step before each executor iteration.
- Overlay merge conflicts are resolved by last-write-wins (explicit field override), which can silently discard base config changes.
- The two-level overlay + per-model YAML dual approach adds conceptual complexity.

---

## Decision 3: Evaluator Co-Evolution

### Problem

As the agent and its harness evolve, the fixed evaluation criteria become less discriminative. The scoring functions (ExactMatchScorer, ExecutionResultScorer, VerifierScorer) were designed for early versions of the agent and don't capture new failure modes that emerged after evolution.

A "fixed yardstick" creates a perverse incentive: the Self-Harness optimizes for the fixed evaluator, potentially discovering harness configurations that score well on the evaluator but regress on real-world tasks.

### Decision

Adopt **evaluator co-evolution**: the evaluation harness that scores agent outputs evolves alongside the agent. Three mechanisms implement this:

1. **ScoringPort extensions**: New scorer implementations can be registered in the DI container without modifying existing scorers. The `JudgePort` abstraction allows model-as-judge evaluation to be swapped independently of the harness.

2. **HarnessMetricScorer**: A structured scorer that reports multi-dimensional metrics (pass rate, task completion, tool efficiency, error rate) rather than a single pass/fail. These metrics feed the RegressionGate's acceptance criteria, so as the harness improves, the scoring bar can be raised.

3. **CodeQualitySignal**: A cheap surrogate signal run during regression validation that catches obvious degradation (unused imports, broken imports, syntax errors) before the full eval suite runs. This signal itself can be versioned and evolved.

### Implementation

- **`ScoringPort`** in `weebot/application/ports/scoring_port.py` — the abstract interface for scorers.
- **`HarnessMetricScorer`** in `weebot/application/services/harness_metric_scorer.py` — multi-dimensional scorer used by the RegressionGate.
- **`CodeQualitySignal`** in `weebot/application/services/code_quality_signal.py` — fast-reject signal for regression validation.
- **`JudgePort`** in `weebot/application/ports/judge_port.py` — model-as-judge evaluation.

### Consequences

**Positive:**
- Evaluation keeps pace with agent evolution — no "fixed yardstick" problem.
- Multi-dimensional metrics provide better signal for regression detection than pass/fail alone.
- CodeQualitySignal prevents wasting eval compute on obviously broken candidates.

**Negative:**
- Evaluator co-evolution can itself overfit to the agent's current behaviour if not checked.
- Maintaining multiple scorer implementations increases the surface area for bugs in evaluation logic.
- The scoring criteria are currently hardcoded — evolving the scoring thresholds is not yet automated.

---

## Relationship to Existing Decisions

| ADR | Relationship |
|-----|-------------|
| ADR-001 (Clean Architecture) | Self-Harness loop flows, resolvers, and scorers all follow port/adapter pattern. `TrajectoryRepositoryPort` and `ScoringPort` extend the port ecosystem. |
| ADR-002 (CQRS) | Failure signatures are emitted as commands via the mediator, stored via handlers, and queried by the harness flow. Events drive the evolution cycle. |
| ADR-005 (Model Cascade) | Per-model harness overlays are tightly coupled to the cascade — each tier can have its own overlay. The resolver is called per-step to adjust instructions for the active model. |

## References

- `REASONIX.md` — project overview, stack, layout, conventions
- `docs/codebase_mindmap.md` — full architecture mind map
- `weebot/application/flows/harness_opt_flow.py` — Self-Harness optimization loop
- `weebot/application/services/model_aware_harness_resolver.py` — per-model overlay resolution
- `weebot/application/services/harness_metric_scorer.py` — multi-dimensional scoring
- `weebot/config/harness/schema.py` — HarnessConfig model
- `weebot/config/harness/v0.2.0.yaml` — base harness config
- `weebot/config/harness/overlays/README.md` — overlay file format
