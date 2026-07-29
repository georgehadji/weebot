# Adaptive Capability Router (ACR) — Implementation Plan

**Project:** weebot
**Document type:** Engineering implementation plan
**Status:** Draft for review
**Date:** 2026-07-09
**Owner:** vivlosbooks

---

## 1. Executive Summary

### 1.1 Objective

Replace weebot's static `task-category → model` mapping with an **Adaptive Capability Router (ACR)**: a closed-loop system that measures per-task-type model performance, scores candidate models by expected utility, selects (with exploration), and updates its own beliefs after every call. The routing decision changes from *"for legal tasks use model X"* to *"for this task, with these constraints, right now, model X has the highest expected utility."*

### 1.2 Key finding from architecture review

**weebot already implements ~70% of the proposed 7-level ACR design under different names.** The proposal (as originally drafted) is over-built and contains two mathematical errors. This plan keeps the sound parts, corrects the errors, and adds only the three genuinely missing pieces.

| Proposed ACR level | Existing weebot component | Verdict |
|---|---|---|
| L1 static registry | `weebot/config/model_registry.py` (`ModelInfo`) | **Exists** — extend with quality axes |
| L1 dynamic registry | `weebot/core/model_cascade_tracker.py` | **Exists** — enrich records |
| L2 capability vector | — | **Build** (quality axes only) |
| L3 requirement vector | `domain/models/agent_capability.py` (partial) | **Extend** to task-level |
| L4 utility scorer | `model_registry.get_cheapest_model_for_task()` (primitive) | **Build** proper scorer |
| L5 telemetry | `model_cascade_tracker.py` | **Exists** — add category + quality |
| L6 online learning | — | **Build** (Thompson sampling) |
| L7 benchmark DB | — | **Defer** (seed priors manually first) |
| Constraint checker | `_cascade.py` (credit + tool-support filters) | **Exists** — consolidate |
| Model selection | `task_model_router.CATEGORY_MODEL` (static) | **Replace** with ACR output |
| Execution | `application/agents/executor/_cascade.py` (`CascadeExecutor`) | **Keep** — consumes ordered list |

### 1.3 Corrections applied to the original design

1. **Mixed-unit cosine similarity is invalid.** The original capability vector packs `reasoning=9.8 … latency=7, cost=5` into one array and cosine-matches. Cost and latency are *penalties*, not capabilities; folding them into a dot product produces a meaningless score dominated by the highest-magnitude axis, and the L4 formula then *subtracts them again* (double-counting). **Fix:** cosine over quality axes only; cost/latency/context handled as separate penalty and constraint terms.
2. **Constraints modeled as soft scores.** Context-window fit and availability are hard (fits or does not). **Fix:** hard-gate in a Constraint Checker *before* scoring, not as a weighted `+ζ·S_context` term.
3. **Redundant knobs.** The original has both per-agent coefficients `α…ζ` *and* a requirement vector. **Fix:** requirement weights **are** the coefficients — collapse to one.
4. **Circular reward signal.** "LLM critic score" as the primary learning reward means a model grades its own family. **Fix:** rank reward by reliability — hard signals (JSON parsed, tool call succeeded, step completed, zero retries) primary; human score next; LLM critic as tiebreak only.
5. **Hand-authored quality scalars are fiction.** `reasoning: 9.8` does not generalize and drifts when a model is silently updated. **Fix:** seed quality axes from published benchmark numbers once; overwrite with measured live performance as telemetry accumulates.

### 1.4 Scope

**In scope:** telemetry enrichment, quality-profile domain model, constraint checker consolidation, utility scorer, Thompson-sampling bandit router, posterior persistence, observability, feature-flagged rollout.
**Out of scope (this phase):** automated benchmark suite execution (L7), reinforcement-learning over the utility function, cross-provider model auto-discovery beyond the existing live-rescue path.

### 1.5 Success criteria

- Cascade hit-rate (FREE/BUDGET success before PREMIUM) improves or holds vs. the static baseline.
- Mean cost-per-successful-step decreases without a statistically significant drop in step success rate.
- Router converges: for a fixed task category, selection distribution stabilizes on the empirically best model within N calls (target N ≤ 200 per category).
- Zero regression when the feature flag is off (byte-for-byte identical routing to today).

---

## 2. Current Architecture Assessment

### 2.1 Layering (Clean / Hexagonal)

weebot enforces inward-pointing dependencies: `Interfaces → Infrastructure → Application → Domain`. ACR must respect this:

- **Domain:** pure data — `CapabilityVector`, `ModelQualityProfile`, `TaskRequirement`, `RouteDecision`. No I/O, no framework imports. Immutable (`pydantic` `frozen=True`, consistent with `agent_capability.py` and `domain/models/*`).
- **Application:** `UtilityScorer`, `AdaptiveCapabilityRouter` (implements the existing `TaskRouterPort`), orchestration. Depends on ports, not adapters.
- **Infrastructure:** `PosteriorRepository` (SQLite, reusing the existing WAL-mode connection pool), telemetry aggregation queries, optional benchmark runner.
- **Core:** `model_cascade_tracker.py` stays where it is (importable without pulling application/infrastructure).

### 2.2 Current routing data flow

```
step description
   │
   ▼
SemanticTaskRouter / task_model_router.classify_step()   ← classification (embedding or keyword)
   │  TaskCategory
   ▼
CATEGORY_MODEL[category]   ← STATIC map (single model)          ◄── replaced by ACR
   │  model_id
   ▼
model_provider callback  →  CascadeExecutor.call_with_cascade()  ← execution (parallel probe → sequential → live rescue)
   │
   ▼
ModelCascadeTracker.record(CascadeDecision)   ← telemetry (no category, no quality)  ◄── enriched by ACR
```

### 2.3 Integration points

- **`application/agents/executor/_base.py`** and **`_cascade.py`** — consume `model_provider(description) -> model_id`. ACR extends this contract to return an **ordered candidate list**; `CascadeExecutor` already tries models in order, so the change is additive.
- **`config/model_refs.py:get_model_cascade_for_role()`** — per-role cascade config; becomes the *fallback* ordering when ACR is disabled or cold.
- **`core/model_cascade_tracker.py`** — the write-side telemetry sink; ACR reads aggregates from it (or its persisted mirror) to update posteriors.
- **`config/model_registry.py:get_cheapest_model_for_task()`** — existing constraint+cost primitive; the Constraint Checker is refactored from and generalizes this.
- **MCP `weebot://costs` resource / web cost dashboard** — already read tracker summaries; extend to expose routing analytics.

### 2.4 Technical debt relevant to ACR

- `task_model_router.py` has **duplicate `_PATTERNS` dictionary keys** (`FILE_OPS`, `REVIEW`, `PLANNING`, `SECURITY` defined twice) — later definitions silently overwrite earlier ones. Must be cleaned when this module is touched (see WBS-0).
- Quality axes live nowhere: `ModelInfo` tracks cost/context/capability *flags* but no reasoning/coding/writing quality. New domain type required.
- Telemetry is session-scoped and in-memory (ring buffer, `maxlen=500`). Online learning needs durable, category-partitioned aggregates → new persistence.
- Two classifiers (keyword + embedding) with overlapping category enums; ACR should depend on the `TaskRouterPort` abstraction, not a concrete classifier.

### 2.5 Security & safety posture

- Model selection must never bypass `weebot/core/bash_guard.py` or the Structured Output validation pipeline — ACR selects *who* runs, not *what* is allowed to run. No change to safety gates.
- Constraint Checker must fail **closed** on capability requirements (e.g. `requires_vision`) and fail **open** on soft availability probes (matching the existing credit pre-check's fail-open behavior) to avoid deadlocking the cascade.
- Posterior store is local, non-sensitive; no secrets. Benchmark prompts must not contain live credentials.

---

## 3. Detailed Implementation Plan

### 3.1 Target architecture

```
                     ┌─────────────────────────┐
                     │   Capability Registry    │  ModelQualityProfile (quality axes)
                     │  (model_registry + new)  │  + ModelInfo (cost/ctx/flags)
                     └────────────┬─────────────┘
                                  │
   step description               ▼
        │            ┌─────────────────────────┐
        ▼            │  AdaptiveCapabilityRouter│  (implements TaskRouterPort)
  TaskRouterPort ──► │  1. classify (category)  │
  classify           │  2. Constraint Checker   │  hard gate: ctx fits? tools? vision? avail?
                     │  3. Utility Scorer       │  U = α·cap + β·quality − δ·cost − ε·latency
                     │  4. Bandit select        │  Thompson over Beta(category,model)
                     └────────────┬─────────────┘
                                  │  ordered candidate list
                                  ▼
                     ┌─────────────────────────┐
                     │      CascadeExecutor     │  (unchanged: probe → fallback → rescue)
                     └────────────┬─────────────┘
                                  │  outcome + quality signals
                                  ▼
                     ┌─────────────────────────┐
                     │   Enriched Telemetry     │  CascadeDecision + category + quality
                     │  (tracker + PosteriorRepo)│
                     └────────────┬─────────────┘
                                  │  Bayesian update (per category×model)
                                  └────────────► Capability Registry (dynamic axes)
```

### 3.2 Phased roadmap

| Phase | Milestone | Depends on | Exit gate |
|---|---|---|---|
| **P0** | Telemetry enrichment + `task_model_router` debt cleanup | — | Every cascade record carries category + quality signals; tests green |
| **P1** | Quality profiles + Constraint Checker + Utility Scorer (deterministic, static priors) | P0 | ACR selects by utility using benchmark-seed priors; behind feature flag; parity test vs. static map |
| **P2** | Thompson-sampling bandit + posterior persistence + online update | P1 | Router converges on synthetic + replayed telemetry; exploration budget capped |
| **P3** | Benchmark engine (prior seeding, periodic refresh) | P1 | Priors auto-seeded on model add; documented cadence |
| **P4** | Observability, dashboards, tuning, GA | P2 | Analytics exposed via MCP/web; flag defaults on; rollback documented |

Phases P1→P2 are the critical path. P3 can proceed in parallel with P2. P4 gates general availability.

### 3.3 Design decisions

- **Router is per-step, not per-agent.** weebot already classifies each step; keep that granularity. The requirement vector is derived from the task category (+ optional overrides), not fixed per agent.
- **Router emits an ordered list, not a single model.** This preserves the existing cascade fallback semantics and makes exploration cheap (explore in the primary slot, keep proven models as fallback).
- **Bandit, not full RL.** Beta-Bernoulli Thompson sampling over `(category, model)` is trivial to implement, needs no reward-shaping, and naturally balances explore/exploit. RL is YAGNI at this scale and lacks a reliable reward.
- **Static map becomes the prior, never deleted.** `CATEGORY_MODEL` and `get_model_cascade_for_role()` define the cold-start ordering and the flag-off fallback.
- **Non-stationarity handled by recency-weighting.** Posteriors decay (sliding window / exponential forgetting) so a silently upgraded model is re-learned rather than locked to stale stats.

---

## 4. Task Breakdown Structure (WBS)

### WBS-0 — Telemetry enrichment & debt cleanup (Phase P0)

**Objective:** Make every cascade outcome attributable to a task category and scored by hard quality signals, so the learning loop has a signal. Remove the duplicate-key bug in the router.

**Affected components:**
- `weebot/core/model_cascade_tracker.py` (`CascadeDecision`, `summary()`)
- `weebot/application/agents/executor/_cascade.py` (record call sites)
- `weebot/application/services/task_model_router.py` (duplicate `_PATTERNS` keys)
- Consumers: `weebot/mcp/resources.py`, web cost API

**Design changes:**
- Extend `CascadeDecision` (frozen dataclass) with:
  - `task_category: str = "general"`
  - `json_valid: bool | None = None`
  - `tool_success: bool | None = None`
  - `retries: int = 0`
  - `critic_score: float | None = None`
  All optional/defaulted → **backward compatible** with existing construction sites.
- Add `ModelCascadeTracker.per_category_stats()` returning `{category: {model: {attempts, successes, mean_latency, mean_cost}}}` for the scorer/bandit to read.
- Merge the duplicate `_PATTERNS` dictionary entries in `task_model_router.py` into single canonical lists per category.

**Implementation tasks:**
1. Add fields to `CascadeDecision`; update docstring.
2. Thread `task_category` from the router through `call_with_cascade(..., description)` to `record(...)`.
3. Capture `json_valid` / `tool_success` from the Structured Output validation pipeline result at the record site.
4. Add `per_category_stats()` aggregation (lock-guarded, like `summary()`).
5. De-duplicate `_PATTERNS`; add a unit test asserting each `TaskCategory` key appears once.

**Refactoring:** None structural; additive fields + one dict de-dup.

**Testing:** Unit — new fields default correctly; `per_category_stats()` aggregates a known fixture; de-dup test. Regression — existing tracker tests unchanged.

**Acceptance criteria:** Cascade records carry category + at least one hard quality signal; `per_category_stats()` returns correct aggregates; no duplicate router keys; all existing tests pass.

**Rollback:** Fields are additive with defaults; revert commit restores prior behavior with no schema migration.

---

### WBS-1 — Quality profiles & Capability Registry extension (Phase P1)

**Objective:** Represent per-model quality on comparable axes, seeded from benchmarks, updatable from telemetry.

**Affected components:** `weebot/domain/models/` (new), `weebot/config/model_registry.py`.

**Design changes:**
- New domain type (immutable):
  ```python
  class CapabilityAxis(str, Enum):
      REASONING = "reasoning"; CODING = "coding"; WRITING = "writing"
      LEGAL = "legal"; MATH = "math"; CITATION = "citation"
      PLANNING = "planning"; TOOL_USE = "tool_use"; LONG_CONTEXT = "long_context"

  class ModelQualityProfile(BaseModel):
      model_config = ConfigDict(frozen=True)
      model_id: str
      axes: dict[CapabilityAxis, float]   # 0..10, benchmark- or telemetry-derived
      source: Literal["benchmark", "telemetry", "seed"] = "seed"
  ```
- **Quality axes only** — cost, latency, context, availability stay in `ModelInfo` / live probes (they are penalties/constraints, not capabilities).
- `TaskRequirement`: `dict[CapabilityAxis, float]` weights per category, plus hard flags (`requires_vision`, `requires_tools`, `min_context`).

**Implementation tasks:**
1. Define `CapabilityAxis`, `ModelQualityProfile`, `TaskRequirement` in domain.
2. Author seed profiles for the actively-routed models (the ~15 in `CATEGORY_MODEL` + role cascades) from published benchmark numbers; store as a YAML/JSON data file loaded at startup (not hardcoded scalars scattered in code).
3. Map each `TaskCategory` → `TaskRequirement` (quality weights + hard flags), replacing implicit knowledge in `CATEGORY_MODEL`.

**Refactoring:** None to existing `ModelInfo`; the new profile is a sibling table keyed by `model_id`.

**Testing:** Unit — profile immutability; every routed model has a seed profile; every `TaskCategory` has a requirement. Schema-validation test on the seed data file.

**Acceptance criteria:** Quality profiles load for all routed models; requirements defined for all categories; no cost/latency axis inside the quality vector.

**Rollback:** New files only; unused unless the scorer (WBS-3) references them.

---

### WBS-2 — Constraint Checker (Phase P1)

**Objective:** Hard-filter candidate models before scoring — one consolidated gate replacing scattered ad-hoc filters.

**Affected components:** new `weebot/application/services/routing/constraint_checker.py`; refactors logic currently inline in `_cascade.py` (`_is_openrouter_model`, credit pre-check, tools-support filter) and `model_registry.get_cheapest_model_for_task()`.

**Design changes:**
- `ConstraintChecker.eligible(candidates, requirement, context_tokens) -> list[str]` applying, in order:
  1. Capability flags — `supports_function_calling` if `requires_tools`; `supports_vision` if `requires_vision` (fail **closed**).
  2. Context fit — `context_tokens <= max_input_tokens` (fail closed).
  3. Availability — circuit-breaker state (`CascadeExecutor.cascade_is_tripped`) and credit pre-check (fail **open** on probe error, matching current behavior).

**Implementation tasks:**
1. Extract the credit/OpenRouter filter and tools-support checks into the checker (keep thin adapters in `_cascade.py` delegating to it — DRY).
2. Unit-test each gate independently and in composition.

**Refactoring:** Move (not duplicate) filter logic out of `_cascade.py`; `CascadeExecutor` calls the shared checker.

**Testing:** Unit — vision/tools requirement excludes non-supporting models; oversized context excluded; tripped breaker excluded; credit-probe failure keeps models (fail-open).

**Acceptance criteria:** Single checker enforces all hard constraints; `_cascade.py` no longer duplicates filter logic; behavior parity on existing cascade tests.

**Rollback:** Keep the old inline filters behind the feature flag until the checker is proven; flag-off path uses original code.

---

### WBS-3 — Utility Scorer (Phase P1)

**Objective:** Rank eligible models by expected utility using corrected math.

**Affected components:** new `weebot/application/services/routing/utility_scorer.py`.

**Design changes:**
```
U(model, task) = α · cap_match            # cosine(profile.axes, requirement weights) — QUALITY AXES ONLY
               + β · live_quality         # success/quality rate for (category, model) from telemetry
               − δ · cost_norm            # normalized $ from ModelInfo.calculate_cost
               − ε · latency_norm         # normalized mean latency from telemetry
```
- Weights `(α, β, δ, ε)` derived from the `TaskRequirement` (no separate per-agent coefficient set).
- `cost_norm` / `latency_norm` min-max normalized across the eligible set per call.
- Cold-start: when telemetry for `(category, model)` is empty, `live_quality` falls back to the benchmark-seeded profile value.

**Implementation tasks:**
1. Implement cosine over the shared axis ordering (guard zero-norm vectors).
2. Implement normalization + the linear combination.
3. Return an ordered `list[RouteCandidate]` with score breakdown (for observability).

**Refactoring:** Generalizes `get_cheapest_model_for_task()`; that function stays for its existing callers but the scorer supersedes it for routing.

**Testing:** Unit —
- higher quality-axis match ranks higher when cost equal;
- cheaper model ranks higher when quality equal;
- cost/latency do **not** enter `cap_match` (regression test guarding the corrected math);
- empty-telemetry path uses benchmark fallback;
- score breakdown sums correctly.

**Acceptance criteria:** Deterministic ranking given fixed inputs; corrected-math guard test passes; scorer consumes only eligible (post-checker) candidates.

**Rollback:** Feature-flagged; flag-off uses `CATEGORY_MODEL`.

---

### WBS-4 — AdaptiveCapabilityRouter + wiring (Phase P1)

**Objective:** Compose classify → constrain → score into a `TaskRouterPort` implementation and wire it into the executor as the model provider.

**Affected components:** new `weebot/application/services/adaptive_capability_router.py`; `application/di/_factories.py`; `application/agents/executor/_base.py`.

**Design changes:**
- Implements `TaskRouterPort`; internally delegates classification to the existing `SemanticTaskRouter` (composition, not reimplementation).
- Output: ordered candidate list. The executor's `model_provider` returns `list[str]`; `CascadeExecutor.call_with_cascade` consumes the ordering (it already tries models sequentially/parallel).
- Feature flag `WEEBOT_ENABLE_ACR` (default off in P1). Flag off → current `model_for_step` path unchanged.

**Implementation tasks:**
1. Router class composing classifier + checker + scorer.
2. DI factory wiring behind the flag; fallback to `task_model_router.model_for_step` when off or on any router exception (fail-safe).
3. Adapt `model_provider` contract to list output; keep single-string back-compat shim.

**Refactoring:** `_base.py` model-provider call site accepts a list; smallest possible diff.

**Testing:** Integration — flag off = byte-identical selection to today (golden test over a corpus of step descriptions); flag on = valid ordered list, first candidate eligible; router exception falls back to static map.

**Acceptance criteria:** Parity test passes flag-off; flag-on produces eligible ordered candidates; no unhandled router exception can break execution.

**Rollback:** Single env flag → instant revert to static routing with no redeploy.

---

### WBS-5 — Thompson-sampling bandit + posterior persistence (Phase P2)

**Objective:** Learn the best model per category online, balancing exploration and exploitation, with durable, recency-weighted beliefs.

**Affected components:** new `weebot/application/services/routing/bandit.py`; new `weebot/infrastructure/persistence/posterior_repository.py` (SQLite, reuse pooled WAL connection).

**Design changes:**
- Beta-Bernoulli posterior per `(category, model)`: `success` = hard-signal-derived reward (step completed ∧ json_valid ∧ tool_success ∧ retries==0), else failure. Critic score only breaks ties, never overrides a hard failure.
- **Selection:** sample `θ ~ Beta(α, β)` per eligible model; combine with the deterministic utility score (Thompson on the quality/reliability term, deterministic penalties for cost/latency) to order candidates.
- **Cold-start:** initialize `Beta` pseudo-counts from the benchmark prior (a strong prior → little early exploration of obviously weak models).
- **Non-stationarity:** exponential forgetting (decay α, β by factor γ<1 on each update) so silent model upgrades are re-learned.
- **Exploration budget:** cap the fraction of traffic that may select a non-top-utility model per category per window; premium-tier models get a stricter cap (exploration costs real money).

**Implementation tasks:**
1. `PosteriorRepository`: schema `(category, model, alpha, beta, updated_at)`; upsert with decay; thread-safe.
2. Bandit sampler + budget guard.
3. `record_outcome(...)` hook called from the executor's `on_success` / failure paths, translating `CascadeDecision` into a reward and updating the posterior.
4. Backfill job: seed posteriors from existing tracker history on first run.

**Refactoring:** Router (WBS-4) gains an optional bandit stage between scorer and output.

**Testing:**
- Unit — Beta update math; decay; budget cap enforced; cold-start uses prior.
- Simulation — synthetic environment where model B is truly better for category X: assert selection share of B exceeds 80% within ≤200 pulls; assert recovery when B's true quality drops mid-stream (non-stationarity).
- Persistence — posterior survives restart; concurrent updates are serialized.

**Acceptance criteria:** Convergence + recovery simulations pass; exploration budget never exceeded; posteriors durable and thread-safe.

**Rollback:** Bandit stage is optional; disabling it reverts to the deterministic scorer (WBS-3) with priors — still an improvement over static.

---

### WBS-6 — Benchmark engine (Phase P3, parallel)

**Objective:** Seed and periodically refresh quality profiles from real measurements instead of hand numbers.

**Affected components:** new `weebot/infrastructure/benchmark/` (runner + suites), profile data file from WBS-1.

**Design changes:** Small, versioned benchmark suites per axis (reasoning, coding, citation, JSON validity, long-context, multilingual/Greek). Runner executes on model add/upgrade and on a scheduled cadence; writes `ModelQualityProfile(source="benchmark")`.

**Implementation tasks:** Define minimal suites; runner with cost guard (benchmarks cost tokens); persist results; wire to profile loader.

**Testing:** Runner produces deterministic scores on a fixture model (mock LLM); cost guard aborts over-budget runs.

**Acceptance criteria:** New model → profile auto-seeded; documented cadence and cost ceiling.

**Rollback:** Fully independent; profiles fall back to manual seeds if the runner is disabled.

---

### WBS-7 — Observability, tuning, GA (Phase P4)

**Objective:** Make routing decisions inspectable and the system tunable; flip the flag on.

**Affected components:** `weebot/mcp/resources.py` (`weebot://costs` → add `weebot://routing`), web cost dashboard, logging/metrics.

**Design changes:** Structured decision logs (category, eligible set, scores breakdown, selected, explore/exploit flag, outcome). Metrics: per-category selection distribution, cascade hit-rate, cost-per-success, convergence indicator. Trace span per routing decision.

**Implementation tasks:** Emit structured logs at decision + outcome; aggregate for the MCP resource; dashboard panel; alerting on hit-rate/cost regression.

**Testing:** Log schema test; MCP resource returns routing analytics; dashboard renders.

**Acceptance criteria:** Every decision is reconstructable from logs; analytics exposed; GA checklist (§8) satisfied → flag defaults on.

**Rollback:** Flag → off restores static routing; observability additive.

---

## 5. Risk & Mitigation Matrix

| # | Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | Mixed-unit cosine reintroduced during implementation | High | Med | Corrected-math guard test (WBS-3); code-review checklist item; axes enum excludes cost/latency by construction |
| R2 | Exploration burns budget on premium models | High | Med | Per-tier exploration budget cap; strong benchmark priors; PREMIUM excluded from primary exploration slot |
| R3 | Non-stationarity — model silently upgraded, posterior stale | Med | High | Exponential forgetting (decay γ); bounded ring-buffer recency; periodic benchmark refresh |
| R4 | Circular reward (critic grades own family) | Med | Med | Hard signals primary; critic tiebreak only; never overrides a hard failure |
| R5 | Cold-start bad decisions before data accumulates | Med | High | Benchmark-seeded priors; flag-off = static map until confident; parity gate before enabling |
| R6 | Router exception breaks step execution | High | Low | Fail-safe fallback to `model_for_step` on any router error; router never in the critical failure path |
| R7 | Backward-compat regression in `model_provider` contract | High | Low | List/string back-compat shim; golden parity test flag-off; additive telemetry fields |
| R8 | Posterior store concurrency corruption | Med | Low | WAL-mode pooled SQLite; lock-guarded upserts; serialized-update test |
| R9 | Duplicate-key bug in `task_model_router` masks a category | Med | High (present now) | Fixed in WBS-0 with a single-key assertion test |
| R10 | Classifier miscategorizes step → wrong requirement | Med | Med | Depend on `TaskRouterPort` abstraction; confidence threshold → fall back to GENERAL requirement; monitored via analytics |
| R11 | Scope creep into full RL / L7 automation | Low | Med | YAGNI boundary in §1.5; RL and auto-benchmark explicitly deferred |
| R12 | Benchmark runs leak credentials or overspend | Med | Low | No secrets in prompts; cost guard aborts over-budget; sandboxed |

---

## 6. Testing & Quality Assurance Strategy

### 6.1 Levels

- **Unit (target ≥80% on new modules):** domain immutability, constraint gates, scorer math (incl. corrected-math regression), bandit update/decay/budget, posterior repo.
- **Integration:** router composed end-to-end; flag-off parity (golden corpus of step descriptions → identical model to today); flag-on eligibility + fallback-on-error.
- **Simulation (bandit):** synthetic and telemetry-replay environments for convergence, recovery under drift, and budget adherence — deterministic seeds for reproducibility.
- **Regression:** full existing `pytest tests/ -v`; architecture-fitness tests (dependency direction) must stay green — ACR domain types import nothing outward.
- **Contract:** ACR satisfies `TaskRouterPort`; add to `test_port_contracts.py`.

### 6.2 Quality gates (CI)

- `pytest -n auto` green; coverage gate on new packages.
- `black` / `isort` / `ruff` clean; type annotations on all new signatures (`mypy`/`pyright`).
- Architecture-fitness suite green (no inward-dependency violations).
- Corrected-math guard test is a **required** check.

### 6.3 Engineering practices applied

- **SOLID / Clean Architecture:** router depends on `TaskRouterPort`, scorer/checker/bandit are single-responsibility services, domain stays pure.
- **DRY:** constraint logic consolidated (WBS-2) rather than duplicated across `_cascade.py` and `model_registry.py`.
- **KISS / YAGNI:** Thompson over RL; manual prior seeding before automated benchmarks.
- **Secure-by-Design / Defensive:** hard constraints fail closed; availability probes fail open; router failure never breaks execution; no bypass of bash-guard or output validation.
- **Observability:** structured decision + outcome logs, per-category metrics, trace spans (WBS-7).
- **CI/CD:** feature-flagged trunk-based rollout; additive migrations only; parity gate before enable.
- **Documentation:** ADR for the routing decision; update `weebot/CLAUDE.md` "Available Tools" / model-cascading section; docstrings on every public method.

---

## 7. Deployment & Rollback Plan

### 7.1 Rollout sequence

1. **P0 ships dark:** telemetry enrichment + debt fix — no behavior change, gathers the category-partitioned data the learner needs.
2. **P1 behind `WEEBOT_ENABLE_ACR=0`:** deterministic scorer with benchmark priors. Enable in a canary/dev session; run the parity + eligibility suite.
3. **Shadow mode (recommended):** run ACR to *log* its choice while still executing the static choice; compare offline for N sessions. No production impact.
4. **P2 enable bandit in canary:** monitor convergence, cost-per-success, hit-rate vs. baseline for a fixed window.
5. **P4 GA:** flip `WEEBOT_ENABLE_ACR=1` by default after the §8 checklist passes.

### 7.2 Feature flags

- `WEEBOT_ENABLE_ACR` — master switch (routing path).
- `WEEBOT_ACR_BANDIT` — bandit stage on/off (falls back to deterministic scorer).
- `WEEBOT_ACR_SHADOW` — log-only mode.
- `OPENROUTER_MIN_CREDITS` — existing; reused by the constraint checker.

### 7.3 Rollback

- **Instant:** set `WEEBOT_ENABLE_ACR=0` — reverts to `CATEGORY_MODEL` / role cascade with no redeploy.
- **Data:** posterior table is additive; drop it to reset learning without affecting execution.
- **Code:** each WBS is a separate, revertible commit; telemetry fields are defaulted (no schema migration to undo).

### 7.4 Migration concerns

- No breaking DB migration — new SQLite table only; existing state/event stores untouched.
- Backfill posteriors from historical tracker data is idempotent and re-runnable.

---

## 8. Post-Implementation Validation Checklist

**Correctness**
- [ ] Corrected-math guard test present and green (cost/latency excluded from `cap_match`).
- [ ] Constraint checker fails closed on capability requirements, open on availability probes.
- [ ] Router exception falls back to static routing (fault-injection test passes).

**Parity & regression**
- [ ] Flag-off produces byte-identical routing to pre-ACR baseline (golden corpus).
- [ ] Full `pytest tests/` green; architecture-fitness suite green; `TaskRouterPort` contract test green.
- [ ] `task_model_router` duplicate-key bug fixed; single-key assertion test present.

**Learning behavior**
- [ ] Convergence simulation: best model selected >80% within ≤200 pulls/category.
- [ ] Recovery simulation: re-learns after mid-stream quality drop.
- [ ] Exploration budget never exceeded; PREMIUM tier respects stricter cap.
- [ ] Posteriors persist across restart; concurrent updates serialized.

**Telemetry & observability**
- [ ] Every cascade record carries `task_category` + ≥1 hard quality signal.
- [ ] Routing decisions reconstructable from structured logs (category, eligible set, scores, explore/exploit, outcome).
- [ ] `weebot://routing` MCP resource + dashboard panel expose per-category distribution, hit-rate, cost-per-success.

**Business metrics (canary window)**
- [ ] Cascade hit-rate ≥ static baseline.
- [ ] Cost-per-successful-step decreased with no significant step-success regression.

**Docs & ops**
- [ ] ADR for adaptive routing merged; `weebot/CLAUDE.md` model-cascading section updated.
- [ ] Rollback verified (flag toggle reverts routing in a live session).
- [ ] Benchmark cost ceiling documented; refresh cadence documented.

---

## Appendix A — Corrected utility function (reference)

```
Eligible set  E = ConstraintChecker.eligible(candidates, requirement, context_tokens)   # hard gate

For m in E:
    cap_match(m)   = cosine( profile[m].axes , requirement.weights )      # QUALITY AXES ONLY, ∈[0,1]
    quality(m)     = telemetry_success_rate(category, m)  or  prior(m)    # cold-start → benchmark prior
    cost_norm(m)   = minmax( ModelInfo[m].calculate_cost(est_in, est_out), over E )
    lat_norm(m)    = minmax( telemetry_mean_latency(category, m), over E )

    U(m) = α·cap_match(m) + β·quality(m) − δ·cost_norm(m) − ε·lat_norm(m)
           where (α, β, δ, ε) come from requirement (the category's priorities)

Order E by:  P2  →  θ_m ~ Beta(α_m, β_m) blended into quality term (Thompson)
             P1  →  deterministic U(m)
Emit ordered list → CascadeExecutor.call_with_cascade
```

## Appendix B — File manifest (new / changed)

| Path | Change | Phase |
|---|---|---|
| `weebot/core/model_cascade_tracker.py` | extend `CascadeDecision`, add `per_category_stats()` | P0 |
| `weebot/application/services/task_model_router.py` | de-dup `_PATTERNS` | P0 |
| `weebot/application/agents/executor/_cascade.py` | thread category to record; delegate filters to checker | P0/P2 |
| `weebot/domain/models/capability.py` | `CapabilityAxis`, `ModelQualityProfile`, `TaskRequirement` | P1 |
| `weebot/config/model_quality_profiles.{yaml,json}` | benchmark-seed profiles | P1 |
| `weebot/application/services/routing/constraint_checker.py` | hard gate | P1 |
| `weebot/application/services/routing/utility_scorer.py` | corrected utility | P1 |
| `weebot/application/services/adaptive_capability_router.py` | `TaskRouterPort` impl | P1 |
| `weebot/application/di/_factories.py` | flag-gated wiring | P1 |
| `weebot/application/agents/executor/_base.py` | list-output `model_provider` | P1 |
| `weebot/application/services/routing/bandit.py` | Thompson sampler | P2 |
| `weebot/infrastructure/persistence/posterior_repository.py` | SQLite posteriors | P2 |
| `weebot/infrastructure/benchmark/` | suites + runner | P3 |
| `weebot/mcp/resources.py` | `weebot://routing` analytics | P4 |
| `tests/unit/test_port_contracts.py` | ACR contract | P1 |

---

*End of plan.*
