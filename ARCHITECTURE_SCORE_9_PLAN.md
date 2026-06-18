# Architecture Remediation Plan v2: 7.5/10 → 9.0/10

**Baseline:** Architecture Audit v3 (2026-06-18) — post-remediation score 7.5/10
**Target:** ≥9.0/10
**Previous remediation:** Phases 1–4 reduced ExecutorAgent (-43%), eliminated 2 deprecated ports, split CQRS handlers, fixed core boundary, and added 53 tests.

---

## Score Breakdown & Gap Analysis

| Dimension | Post-Remediation | Target | Gap | Largest Contributor |
|---|---|---|---|---|
| Layer Separation | 9/10 | 10/10 | 1 | Zero top-level runtime infra imports in application. 9 remaining are TYPE_CHECKING/lazy — acceptable. |
| Abstraction Discipline | 5/10 | 9/10 | 4 | 30/59 ports have single implementations. Port count inflated 4× over necessary. |
| Module Cohesion | 7/10 | 9/10 | 2 | `_base.py` 803 lines (target 450). `plan_act_flow.py` 823 lines with 23 imports. `query_handlers.py` 445 lines. |
| Coupling Control | 7/10 | 9/10 | 2 | `plan_act_flow.py` is the single highest-risk coupling hotspot — 23 unique weebot imports. `_global_pool` browser singleton. |
| Async Hygiene | 9/10 | 9/10 | — | Already solid. No sync blocking in async paths. |
| Failure Semantics | 9/10 | 10/10 | 1 | Circuit breaker, retry, cascade all well-defined. Missing integration tests for cascade. |
| Testability | 7/10 | 9/10 | 2 | `_global_pool` has no test reset. Missing `test_cascade_integration.py`. Port contract tests skip 30 single-impl ports. |
| Scalability Readiness | 5/10 | 7/10 | 2 | SQLite ceiling identified. PostgreSQL scaffolded but not default. PlanActFlow stateful per-session. |

---

## Phase 1: Port Surface Rationalization (Week 1)

### Goal: Reduce 59 ports → ~20 ports. Delete single-implementation abstractions.

### Step 1.1 — Audit every port for planned polymorphism

For each of the 59 ports in `weebot/application/ports/`, classify:
- **KEEP** — has ≥2 implementations today OR planned polymorphism within 6 months
- **DELETE** — single implementation, no planned polymorphism

**KEEP list (estimated ~20):**

| Port | Implementations | Reason |
|---|---|---|
| `LLMPort` | 4 | Multi-provider |
| `SandboxPort` | 4 | Multi-backend |
| `ScoringPort` | 3 | Multi-strategy |
| `NotificationPort` | 3 | Multi-channel |
| `StateRepositoryPort` | 3 | SQLite + PostgreSQL + InMemory |
| `SkillIndexPort` | 3 | Multi-source |
| `AnalyticsSinkPort` | 2 | Parquet + OTEL |
| `KnowledgeGraphPort` | 2 | SQLite + PostgreSQL |
| `ProfileStoragePort` | 2 | File + InMemory |
| `RagPort` | 2 | QMD + NoOp |
| `JudgePort` | 2 | ModelJudge + ScoreJudge |
| `TaskRouterPort` | 2 | Keyword + Parallel |
| `StepEvaluatorPort` | 2 | NoOp + LLM |
| `SkillRetrieverPort` | 2 | BM25 + Reranking |
| `SkillStorePort` | 1* | Planned: in-memory implementation for fast tests |
| `TrajectoryRepositoryPort` | 1* | Planned: PostgreSQL for scaling trigger |
| `EventBusPort` | 1* | Planned: SwarmEventBus activation |
| `EventStorePort` | 1* | Planned: Durable store for compliance |
| `FileStoragePort` | 1* | Planned: S3 adapter for cloud deployment |
| `ToolRepositoryPort` | 1* | Planned: >100 tools triggers |

\* Single-impl today but polymorphism planned.

**DELETE list (~39 ports, estimated ~3,000 lines removed):**

The 39 single-implementation ports without planned polymorphism. Each follows the same pattern: delete the port ABC file, remove the DI registration, merge the adapter class into the single consumer or keep as concrete class.

| Port | Adapter | Consumer |
|---|---|---|
| `BackendPort` | `ConfigAdapter` | 1 DI binding |
| `BrowserPort` | `PlaywrightAdapter` | 1 DI binding |
| `CheckpointPort` | `SQLiteCheckpointStore` | 1 DI binding |
| `ConfigPort` | `ConfigAdapter` | 1 DI binding |
| `DesktopPort` | `DesktopAdapter` | 1 DI binding |
| `MCPToolPort` | `MCPClientManager` | 1 DI binding |
| `MemoryPort` | `FilesystemMemoryAdapter` | 1 DI binding |
| `MetricsPort` | `PrometheusAdapter` | 1 DI binding |
| ... | ... | ... |

**Verification:**
- `ls weebot/application/ports/*.py | wc -l` ≤ 22
- All remaining ports have ≥2 implementations OR documented planned polymorphism
- `python -m pytest tests/unit/test_port_contracts.py -v` — all tests pass
- `python -c "from weebot.application.di import Container; c=Container(); c.configure_defaults()"`

**Risk:** LOW — mechanical deletion with search_content verification before each removal.

---

### Step 1.2 — Create concrete registrations for deleted ports

For each deleted port, update the DI container to register the concrete adapter directly:

```python
# Before: self.register(ConfigPort, lambda: ConfigAdapter())
# After:  self.register_instance(ConfigAdapter())
```

**Verification:** DI container produces a working system with all existing integration points.

---

## Phase 2: Orchestrator Decoupling (Weeks 2-3)

### Goal: Reduce `plan_act_flow.py` coupling from 23 imports → ~15 imports. Extract state routing. Reduce `_base.py` from 803 → ~550 lines.

### Step 2.1 — Extract `FlowRouter` from `plan_act_flow.py`

`plan_act_flow.py:385-410` handles state dispatch as an inline block. Extract to `weebot/application/flows/flow_router.py`:

```python
class FlowRouter:
    """Routes between flow states based on plan status and step results."""
    
    def __init__(self, states: dict[str, FlowState]):
        self._states = states
    
    def next_state(self, context: PlanActFlow) -> FlowState:
        ...
```

**Expected outcome:** `plan_act_flow.py` imports drop from 23 → ~19. State routing becomes testable in isolation.

**Risk:** MEDIUM — behavioral extraction requires full test coverage on state transitions.

---

### Step 2.2 — Extract `execute_step` sections into collaborators

`_base.py:execute_step` (lines 285-774, 489 lines) contains three separable concerns:

| Section | Lines | Extract To |
|---|---|---|
| Conversation-building preamble + system prompt load + context window setup | ~80 lines | `_base.py` constructor / `prepare_step()` |
| Tool result processing + vision-in-the-loop + stuck-loop detection | ~150 lines | `_error_handler.ExecutionLoopState` (expand existing) |
| Final error/abort handling + step budget exhaustion | ~60 lines | `_error_handler.build_stuck_error` (already extracted) |

**Expected outcome:** `execute_step` → ~200 lines. `_base.py` → ~620 lines (from 803).

**Risk:** MEDIUM — the stuck-loop detection touches `self._step_budget`, `self._max_steps`, `self._conversation_buffer`, and `self._facts`. Needs careful delegation.

---

### Step 2.3 — Split `query_handlers.py` into 2-3 files

`weebot/application/cqrs/handlers/query_handlers.py` is 445 lines with 11 handler classes. Split by domain:

| New File | Handlers |
|---|---|
| `handlers/session_queries.py` | `GetSessionHandler`, `GetSessionStatusHandler`, `ListSessionsHandler`, `GetSessionHistoryHandler`, `SearchSessionsHandler`, `GetSimilarSessionsHandler` |
| `handlers/plan_queries.py` | `GetPlanHandler`, `GetPlanVisualizationHandler` |
| `handlers/meta_queries.py` | `GetActiveTasksHandler`, `GetActiveSessionsHandler`, `GetCostSummaryHandler` |

**Expected outcome:** Each file ≤ 200 lines.

**Risk:** LOW — mechanical refactor with no logic changes.

---

## Phase 3: Mutable State Elimination (Week 3)

### Step 3.1 — Replace `_global_pool` browser singleton with DI-managed instance

`weebot/infrastructure/browser/session_pool.py:407` — module-level `_global_pool`.

**Fix:** Remove `get_global_pool()` / `close_global_pool()`. Register `BrowserSessionPool` as a singleton in the DI container. Add `reset()` method for test isolation.

**Verification:**
- `search_content "_global_pool"` returns zero matches
- Browser tests can create/destroy pools without cross-contamination

**Risk:** LOW — DI container already manages similar lifecycles.

---

### Step 3.2 — Add `reset_global_pool()` to conftest fixture

After Step 3.1, add pool reset to the existing `_isolate_weebot_settings` fixture. This ensures browser tests are fully hermetic.

---

## Phase 4: Test Coverage & Documentation (Week 4)

### Step 4.1 — Cascade executor integration tests

Create `tests/integration/test_cascade_integration.py`:

| Test | What It Verifies |
|---|---|
| `test_parallel_probes_dispatch_correct_models` | Role cascade resolves to expected model IDs |
| `test_first_completed_cancels_pending` | Successful probe cancels in-flight tasks |
| `test_sequential_fallback_after_parallel_exhaustion` | Tier2/Tier3 models tried serially |
| `test_live_model_rescue_on_all_404` | OpenRouter free models fetched and tried |
| `test_fast_fail_reduces_remaining_timeouts` | Auth/404 errors trigger 15s reduction |
| `test_all_models_tripped_error` | Cascade exhausted → `AllModelsTrippedError` |
| `test_circuit_breaker_prevents_retry` | Tripped model returns None immediately |
| `test_per_model_circuit_breaker_isolation` | Tripping model-A doesn't affect model-B |

**Target:** ≥8 integration tests with real LLM calls (gated behind `--integration` flag or `WEEBOT_INTEGRATION_TESTS=1` env var).

---

### Step 4.2 — Expand architecture fitness tests

Add to `tests/unit/test_architecture_fitness.py`:

| Test | What It Checks |
|---|---|
| `test_plan_act_flow_imports_under_20` | `plan_act_flow.py` imports ≤ 20 unique weebot modules |
| `test_no_module_level_global_pool` | No `_global_pool: Optional[...] = None` patterns outside DI |
| `test_ports_have_documented_polymorphism` | Every single-impl port has a comment explaining WHY it's kept |
| `test_cascade_integration_test_exists` | `test_cascade_integration.py` file present |
| `test_query_handlers_split` | No handler file > 250 lines in `handlers/` |

---

### Step 4.3 — Update ARCHITECTURE.md

- Bump score to 9.0/10
- Add ADR-008: Port Rationalization v2 — "Delete single-implementation ports without planned polymorphism"
- Add ADR-009: FlowRouter Extraction — "Extract state-transition routing from PlanActFlow"
- Update "Known Technical Debt" table: close D15-D17, add new items for remaining work
- Update enforcement section with new fitness tests

---

## Phase 5: Scaling Readiness (Trigger-Gated — Ongoing)

| Trigger | Action |
|---|---|
| >5 concurrent users | Make PostgreSQL the default state repository |
| >10 concurrent users | Externalize session state to Redis |
| Multi-process deployment | Redis/RabbitMQ task queue |
| >100 tool definitions | Enforce `ToolRepositoryPort` for ALL tool access |
| Cross-session agent communication | Activate `SwarmEventBusPort` |

---

## Score Projection After Remediation

| Dimension | Current | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Target |
|---|---|---|---|---|---|---|
| Layer Separation | 9 | 9 | 9 | 9 | 10 | **10** |
| Abstraction Discipline | 5 | 8 | 8 | 8 | 9 | **9** |
| Module Cohesion | 7 | 7 | 9 | 9 | 9 | **9** |
| Coupling Control | 7 | 7 | 8 | 9 | 9 | **9** |
| Async Hygiene | 9 | 9 | 9 | 9 | 9 | **9** |
| Failure Semantics | 9 | 9 | 9 | 9 | 10 | **10** |
| Testability | 7 | 7 | 7 | 8 | 9 | **9** |
| Scalability Readiness | 5 | 5 | 5 | 6 | 7 | **7** |
| **Overall** | **7.5** | **7.6** | **8.3** | **8.6** | **9.1** | **9.1** |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Port deletion breaks undiscovered dynamic import | Low | High | `search_content` before every delete; CI catches import errors |
| `FlowRouter` extraction changes state-transition behavior | Medium | High | Full test suite on state transitions before/after |
| `execute_step` section extraction introduces subtle bugs | Medium | High | Extract one section at a time; full test run between each |
| Integration tests require OpenRouter credits | High | Low | Gate behind env var; make optional in CI |
| Browser pool DI migration breaks session cleanup | Low | Medium | Existing browser tests catch regressions |

---

## Definition of Done

- [ ] Port count: ≤22 (down from 59)
- [ ] Every remaining port has ≥2 implementations OR documented planned polymorphism comment
- [ ] `plan_act_flow.py`: ≤19 unique weebot imports (down from 23)
- [ ] `_base.py`: ≤620 lines (down from 803)
- [ ] `query_handlers.py` split into ≤3 files, each ≤200 lines
- [ ] `_global_pool` browser singleton eliminated
- [ ] `test_cascade_integration.py`: ≥8 integration tests
- [ ] Architecture fitness tests: 40+ (up from 35)
- [ ] `ARCHITECTURE.md`: score 9.0/10, ADR-008, ADR-009 added
- [ ] Full test suite: 270+ tests, 0 failures
