# Self-Harness Implementation Plan for Weebot

**Based on:** *"Self-Harness: Harnesses That Improve Themselves"* (Zhang et al., arXiv:2606.09498v1, Shanghai AI Lab, 2026)
**Status:** Draft — 7 phases, 61 items, ~42 files (28 new, 14 modified)

---

## Paper Summary

Self-Harness enables an LLM-based agent to iteratively improve its own operating harness — the system prompts, instructions, tools, runtime policies, and orchestration rules. Three-stage loop:

1. **Weakness Mining** — cluster failed traces by `(verifier_cause, agent_behavior, mechanism)` triples
2. **Harness Proposal** — same model proposes K diverse yet minimal candidate edits, each targeting one failure mechanism
3. **Proposal Validation** — promote only if Δ_in ≥ 0 AND Δ_ho ≥ 0 AND max(Δ_in, Δ_ho) > 0

## Weebot Alignment

| Paper Component | Weebot Equivalent | Status |
|---|---|---|
| Execution traces + verifier outcomes | `TrajectoryRepository` (SQLite), `TrajectorySummary` with `failure_modes` / `score` / `passed` | ✅ Exists |
| Per-trajectory degenerate pattern detection | `TrajectoryHealth` enum (`REPEATING`, `SEMANTIC_LOOP`, etc.) | ✅ Exists |
| Versioned harness config with lineage | `HarnessConfig` (Pydantic, YAML-backed) with `version`, `evolved_from` | ✅ Exists (structural only) |
| Rollout→Reflect→Merge→Validate→Accept loop | `SkillOptFlow` + `OptimizerPort` + CQRS validation gate | ✅ Exists (skill-level only) |
| Self-improvement patch system | `SelfImprovementPort` / `SelfImprovementPatch` / `SelfImprover` | ✅ Exists |
| Append-only audit log | `MetaImprovementLog` (SQLite) | ✅ Exists |
| A/B comparison | `ComparisonRunner` / `ComparisonReport` | ✅ Exists |
| Held-in/held-out split with promotion rule | — | ❌ Not implemented |
| Cross-session failure clustering | — | ❌ Not implemented |
| Behavioral harness surfaces | — | ❌ Not in HarnessConfig |
| `OptimizationTarget` protocol (generalize SkillOptFlow) | — | ❌ Not extracted |
| Model-aware harness resolution at runtime | — | ❌ Not implemented |
| Safety surface classification | — | ❌ Not implemented |

## Phases

### Phase 1: Extend HarnessConfig with Behavioral Surfaces
**New:** `weebot/domain/models/harness_instructions.py` — `InstructionConfig`, `RuntimeControlConfig`, `SubagentConfig`, `SkillSelectionConfig`  
**New:** `weebot/config/harness/v0.2.0.yaml` — default behavioral harness  
**New:** `weebot/application/services/harness_prompt_assembler.py` — assembles system prompt from HarnessConfig  
**Modify:** `weebot/config/harness/schema.py` — add 4 new fields to `HarnessConfig`  
**Modify:** `weebot/application/models/plan_act_flow_config.py` — add `harness_config` field  
**Modify:** `weebot/application/flows/plan_act_flow.py` — inject harness prompt at flow start

### Phase 2: Failure Signature Extraction (via CQRS)
**New domain models:** `FailureSignature`, `EvidenceBundle`, `FailureCluster`  
**New CQRS commands:** `ExtractFailureSignatureCommand`, `ClusterFailurePatternsQuery`  
**New CQRS handlers:** extract triple via LLM, cluster by exact match  
**Modify:** `TrajectoryRepository` — add `failure_signatures` table + methods  
**Modify:** `ScoreTrajectoryCommand` handler — emit `ExtractFailureSignatureCommand` on failure

### Phase 3: Harness Optimizer Infrastructure
**New protocol:** `OptimizationTarget` (ABC) — `load()`, `apply_edits()`, `save()`, `rollback()`  
**New implementations:** `SkillOptimizationTarget`, `HarnessOptimizationTarget`  
**Refactor:** `SkillOptFlow` — parameterize on `OptimizationTarget` instead of hardcoding `Skill`+`SkillStore`  
**New flow:** `HarnessOptFlow` — inherits refactored loop, targets HarnessConfig  
**New CQRS command:** `ApplyHarnessEditsCommand`

### Phase 4: Held-Out Regression Gate
**New service:** `RegressionGate` — progressive validation (held-in first, held-out only if Δ_in≥0)  
**New CQRS behavior:** `HarnessValidationBehavior` — wires into command pipeline  
**New model:** `PromotionDecision`  
**Budget-tier model for validation runs** (`MODEL_BUDGET`)

### Phase 5: Model-Aware Harness Resolution
**New service:** `ModelAwareHarnessResolver` — resolves per LLM call, not statically at flow start  
**Modify:** `PlanActFlow._format_executor_prompt()` — dynamic resolution per step boundary  
**Directory:** `weebot/config/harness/overlays/` — model-specific instruction deltas

### Phase 6: Safety Gate for Autonomous Edits
**New service:** `HarnessSafetyGate` — classifies `AUTONOMOUS_SURFACES` vs `GATED_SURFACES`  
**Modify:** `HarnessValidationBehavior` — check safety before promotion  
**Gated surfaces require user approval** via existing `WaitForUserEvent` pattern

### Phase 7: End-to-End Autonomous Loop
**CLI command:** `python -m cli.main harness evolve [--iterations 3]`  
**Cron job:** `self-harness-weekly` in `weebot/config/jobs.yaml`  
**Integration tests:** full loop with synthetic tasks

## Dependency Graph
```
Phase 1 ─────────────────────────────────────────────────────────────────┐
    │                                                                     │
    ├──→ Phase 2 ──────────┐                                              │
    │         │             │                                              │
    │         └──→ Phase 4 ─┐                                              │
    │                       │                                              │
    └──→ Phase 3 ──────────┤                                              │
              │             │                                              │
              └──→ Phase 5 ─┤                                              │
                       │     │                                              │
                       └──→ Phase 6 ────┐                                  │
                                │        │                                  │
                                └──→ Phase 7 ──────────────────────────────┘
```
