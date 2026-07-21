# Architecture Score Improvement Plan — V3 (6.5 → 8.5+)

**Baseline:** `docs/arch_audit_v3.md` (2026-07-21) — score **6.5/10**  
**Target:** **8.5+/10**  
**Last updated:** 2026-07-21 (post-Valkey migration)  
**Status tracker:** 2 of 11 gaps partially addressed since baseline

### Progress since baseline

| Gap | Status | Commit |
|-----|--------|--------|
| Dead code (RedisEventBus → ValkeyEventBus) | ✅ Defect fixed, renamed, backward-compat alias | `7c180c4` |
| In-memory event bus → Valkey | ⚠️ Class ready, not yet wired into DI | — |

---

## Score Gap Analysis

| Gap | Current | Target | Score Impact | Must Fix? |
|-----|---------|--------|-------------|-----------|
| B1: God Executor (`_base.py` 1083 lines) | HIGH | ≤650 | +0.5 | ✅ Yes |
| B2: God Orchestrator (`plan_act_flow.py` 996 lines) | HIGH | ≤700 | +0.5 | ✅ Yes |
| CQRS overhead (17 handlers) | MEDIUM | ≤10 | +0.2 | ⚠️ High value |
| Premature abstractions (40+ single-impl ports) | MEDIUM | ≤30 | +0.2 | ⚠️ High value |
| Import-linter ignores (60) | MEDIUM | ≤30 | +0.2 | ⚠️ Priority |
| Shared DB coupling | MEDIUM | DatabaseRouter active | +0.2 | ✅ Yes |
| Temporal coupling (hard-coded state machine) | MEDIUM | StateGraph wired | +0.15 | ⚠️ Priority |
| Dead code (RedisEventBus, StateGraph) | LOW | Wired or removed | +0.1 | ✅ Yes |
| Hidden monolith (tight intra-app coupling) | MEDIUM | FlowDependencies factory | +0.15 | ⚠️ Priority |
| Anemic domain model | LOW | 5+ new behavior methods | +0.05 | Optional |
| In-memory event bus (no horizontal scale) | MEDIUM | RedisEventBus active | +0.15 | ✅ Yes |

**Total recovery potential:** ~2.2 points → theoretical ceiling 8.7. Resolving all HIGH items secures ~1.0; resolving top 5 MEDIUM items secures another ~0.8.

---

## Phase 1: Complete God Module Decomposition (Week 1-2) · +1.0 point

### 1A: Wire ExecutorAgent Extraction Files

**Current state:** `_prompt_builder.py` (119 lines) and `_iteration_guard.py` (116 lines) exist but `_base.py` still contains the inlined logic. No imports of these modules anywhere.

| Step | Action | Lines Saved | Risk |
|------|--------|-------------|------|
| 1 | Replace prompt assembly block (`_base.py:403-520`) with `build_executor_prompt()` call from `_prompt_builder.py` | ~120 lines | LOW — pure function, no side effects |
| 2 | Replace loop state initialization (`_base.py:565-589`) with `IterationGuard(step_id=...)` | ~25 lines | LOW — dataclass state only |
| 3 | Replace budget cap check (`_base.py:591-624`) with `IterationGuard.is_tool_call_budget_exhausted()` | ~30 lines | MEDIUM — changes control flow |
| 4 | Replace stuck-detection logic (`_base.py:689-712`) with `IterationGuard.is_assistant_turn_loop()`/`build_stuck_error()` | ~20 lines | MEDIUM — behavioral change |
| 5 | Replace repeated-tool-call detection (`_base.py:726-742`) with `IterationGuard.is_tool_signature_loop()` | ~15 lines | LOW |

**Outcome:** `_base.py` 1083 → ~850 lines. Test after each step with existing executor unit tests.

### 1B: Wire PlanActFlow Extraction Files

**Current state:** `_checkpoint_scheduler.py` (68 lines) and `_iteration_context.py` (36 lines) exist. `PlanActFlowConfig` exists. State routing still hard-coded in `flow_router.py`.

| Step | Action | Lines Saved | Risk |
|------|--------|-------------|------|
| 1 | Replace `_maybe_save_checkpoint()` method body with `CheckpointScheduler.maybe_save()` delegation | ~40 lines saved in `plan_act_flow.py` | LOW — self-contained method |
| 2 | Bundle `_session`, `_plan`, `_step_execution_counts`, `_similar_plan_count`, `_awm` into `IterationContext` dataclass | ~60 lines | MEDIUM — touches the while-loop |
| 3 | Extract `FlowDependencies` factory class that builds `PlannerAgent`, `ExecutorAgent`, `FactResolver`, etc. from config | ~30 lines removed from `__init__` | MEDIUM — service construction |
| 4 | Convert service construction to use `FlowDependencies.build()` in `__init__` | ~140 lines removed from `__init__` | HIGH — orchestrator init path |

**Outcome:** `plan_act_flow.py` 996 → ~750 lines. `__init__` from ~190 → ~50 lines.

### 1C: Complete StateGraph Wiring

**Current state:** `state_graph.py` (142 lines) exists. `FlowRouter._route_product_gate()` and `FlowRouter._route_plan_approval()` implemented. `build_default_state_graph()` is dead code — never imported.

| Step | Action | Risk |
|------|--------|------|
| 1 | Import and call `build_default_state_graph()` in `FlowRouter.resolve_initial_state()` | MEDIUM — replaces the priority-based routing |
| 2 | Add `resolve()` call that walks transitions instead of hard-coded if/elif chain | MEDIUM |
| 3 | Run full E2E flow test to verify state transitions are identical | Required |

**Outcome:** State transitions declarative. Dead code activated. Temporal coupling reduced.

---

## Phase 2: Structural Fixes (Week 2-3) · +0.65 point

### 2A: CQRS Simplification (17 → ≤10 handlers)

| Handler | Action | Reason |
|---------|--------|--------|
| `session_queries.py` | Collapse into `StateRepositoryPort` direct call | Single SELECT, no transaction |
| `plan_queries.py` | Collapse into `StateRepositoryPort` direct call | Single SELECT |
| `active_queries.py` | Collapse into `StateRepositoryPort` direct call | Single SELECT |
| `compact_memory_handler.py` | Collapse into `MemoryCompactor` direct call | Single service call |
| `cancel_session_handler.py` | Collapse into `TaskRunner.cancel_session()` | Thin wrapper |
| `archive_session_handler.py` | Collapse into `StateRepositoryPort` direct | Thin wrapper |
| `failure_signature_handlers.py` | Keep — multi-step transaction | Real CQRS value |
| `create_plan_handler.py` | Keep — multi-step | Real CQRS value |
| `execute_step_handler.py` | Keep — multi-step | Real CQRS value |
| `harness_edit_handler.py` | Keep — complex workflow | Real CQRS value |

**Outcome:** 7 handlers removed → 10 remain. Mediator kept for multi-step operations only.

### 2B: Port Consolidation (63 → ≤45)

Target the lowest-hanging single-implementation ports:

| Port | Action | Why |
|------|--------|-----|
| `analytics_port.py` | Remove; register adapter directly in DI | 1 impl, never swapped |
| `tracing_port.py` | Remove; register adapter directly | 1 impl, OpenTelemetry only |
| `config_port.py` | Remove; use `WeebotSettings` directly | 1 impl, `ConfigAdapter` thin wrapper |
| `metrics_port.py` | Remove; register `PrometheusMetricsAdapter` directly | 1 impl, already bridged by `metrics_bridge.py` |
| `rerank_port.py` | Keep — multiple rerank providers possible | |
| `desktop_port.py` | Keep — platform-specific, may get macOS/Linux | |
| `dreamer_port.py` | Keep — agent-level port | |
| `soul_provider_port.py` | Keep — filesystem vs database variants | |

**Outcome:** 4 ports removed → 59. Additional merge candidates in follow-up.

### 2C: ValkeyEventBus Activation (2/5 complete)

| Step | Action | Risk | Status |
|------|--------|------|--------|
| 1 | ~~Fix publish routing defect~~ — Done in `b746057` | — | ✅ Complete |
| 2 | ~~Rename Redis→Valkey with backward compat~~ — Done in `7c180c4` | — | ✅ Complete |
| 3 | Register `ValkeyEventBus` in DI container (`WEEBOT_VALKEY_URL` gate) | LOW | ⬜ TODO |
| 4 | Keep `AsyncEventBus` fallback when Valkey unavailable | — | ✅ Built-in |
| 5 | Add integration test: publish → subscribe → verify delivery | Required | ⬜ TODO |

**Outcome:** 2/5 steps done. Defect fixed, class renamed + alias. DI wiring + test remain.

### 2D: DatabaseRouter Activation

| Step | Action | Risk |
|------|--------|------|
| 1 | Create `SplitDatabaseRouter` implementing `DatabaseRouterPort` | LOW |
| 2 | Map entity types: `"sessions"` → `weebot_sessions.db`, `"memory"` → `weebot_memory.db`, `"rules"` → `weebot_rules.db` | LOW |
| 3 | Update `_ensure_schema()` to create only the tables for the routed DB | MEDIUM |
| 4 | Add Alembic migration to move tables | HIGH — DB migration |
| 5 | Dual-write for 1 release cycle | MEDIUM |

**Outcome:** Components no longer share a single SQLite file. Schema changes in one domain don't risk others.

---

## Phase 3: Polish & Import-Linter Cleanup (Week 3) · +0.4 point

### 3A: Import-Linter Ignore Reduction (60 → ≤30)

| Contract | Current | Target | How |
|----------|---------|--------|-----|
| `tools-no-infra` | 20 | ≤15 | Fix 5 real violations by injecting ports |
| `interfaces-no-infra` | 28 | ≤15 | Consolidate web router DI into `dependencies.py` |
| `infra-no-app-services` | 8 | ≤6 | Move `interface_customization` to infra |
| `core-no-app` | 5 | ≤4 | Already documented — ADR-009 sunset |

Specific actions:
- Move `weebot.tools.advanced_browser` imports from infrastructure to port injection (3 ignores → 0)
- Move `weebot.interfaces.web.routers.ops_router` CQRS mediator import to `dependencies.py` (1 ignore)
- Merge `weebot.tools.python_tool` + `weebot.tools.bash_tool` sandbox imports under single `SandboxPort` injection (2 ignores → 0)

### 3B: Domain Model Enrichment

Add remaining behavior methods:

| Model | Method | Logic |
|-------|--------|-------|
| `Plan` | `step_budget_remaining(cap: int)` → `int` | Already added in Phase D as `remaining_budget()` ✅ |
| `Plan` | `validate_step_descriptions()` → `list[str]` | Returns warnings for duplicate/empty descriptions (currently in reviewer) |
| `Session` | `has_pending_approval()` → `bool` | Checks `context.get("plan_pending_approval")` |
| `Step` | `is_blocked()` → `bool` | Checks if step depends on incomplete predecessor |

**Outcome:** 2 new methods on domain models. Moves logic from services → domain.

### 3C: Hidden Monolith Mitigation

| Action | Effect |
|--------|--------|
| Extract `FlowDependencies` factory (from Phase 1B) | Reduces `PlanActFlow.__init__` coupling |
| Convert `PlannerAgent` + `ExecutorAgent` service construction to a `FlowDependencies.build()` classmethod | Services constructed in one place, not scattered through `__init__` |
| Add `AgentFactoryPort` with `create_planner()`, `create_executor()` methods | Future-swappable agent implementations |

---

## Score Trajectory

| Phase | Duration | Score | Key Milestone |
|-------|----------|-------|---------------|
| Baseline | — | **6.5** | ARCH-AUDIT-V2 |
| Phase 1 (decomposition) | Week 1-2 | **7.5** | God modules under 850/750 lines. StateGraph wired. |
| Phase 2 (structural fixes) | Week 2-3 | **8.2** | CQRS ≤10 handlers. Ports ≤55. RedisEventBus active. DB router active. |
| Phase 3 (polish) | Week 3 | **8.5+** | Import-linter ≤30 ignores. Domain enriched. Hidden monolith mitigated. |

---

## Verification Plan

### Per-Phase Gates

| Phase | Gate |
|-------|------|
| All | `pytest tests/unit/test_architecture_fitness.py -q` — no new failures |
| All | `lint-imports --config .importlinter` — no new broken contracts |
| 1A | `wc -l weebot/application/agents/executor/_base.py` ≤ 850 |
| 1B | `wc -l weebot/application/flows/plan_act_flow.py` ≤ 750 |
| 1C | `python -c "from weebot.application.flows.state_graph import build_default_state_graph; print('OK')"` |
| 2A | `find weebot/application/cqrs/handlers -name '*.py' | wc -l` ≤ 10 |
| 2C | Integration test: Redis pub → sub delivers event |
| 3A | `lint-imports --config .importlinter` ignore count ≤ 30 |

### Final Validation

Re-run ARCH-AUDIT-V2 after Phase 3. Expected:
- **CRITICAL:** 0
- **HIGH:** 0
- **MEDIUM:** ≤3 (acceptable for >8.5)
- **Score:** ≥8.5

---

## Risk Assessment

| Risk | Phase | Probability | Impact | Mitigation |
|------|-------|------------|--------|------------|
| ExecutorAgent wiring breaks execute_step | 1A | Medium | High | Wire one extraction at a time; run executor tests after each |
| PlanActFlow __init__ refactor breaks service construction | 1B | High | High | Keep legacy kwargs path behind feature flag for 1 sprint |
| StateGraph transition behavior differs from FlowRouter | 1C | Medium | High | Run full E2E flow tests; compare state outputs for 20 test sessions |
| CQRS collapse breaks command callers | 2A | Medium | Medium | Replace handlers with deprecation warning for 1 release |
| DB split corrupts data | 2D | High | Critical | Test migration on production-sized backup; dual-write for 1 cycle |
| Redis dependency breaks existing deployments | 2C | Low | Low | WEEBOT_REDIS_URL gate; Auto-fallback with in-memory bus |

---

## Total Effort

| Phase | Days (1 engineer) | Key Constraint |
|-------|-------------------|----------------|
| Phase 1 | 6–8 | Deep knowledge of PlanActFlow/ExecutorAgent internals |
| Phase 2 | 5–7 | DB migration needs production snapshot testing |
| Phase 3 | 3–4 | Mechanical refactoring; safe |
| **Total** | **14–19 days** | ~3 weeks |

With 2 engineers: ~1.5 weeks (Phase 1 parallelized across B1/B2).

---

*Plan version: 3.0 · Based on ARCH-AUDIT-V2 findings · References specific line numbers and expected outcomes*
