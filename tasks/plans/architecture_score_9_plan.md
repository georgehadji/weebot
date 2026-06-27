# Weebot Architecture Improvement Plan — Target Score >9/10

**Baseline:** 6/10 (audit 2026-06-19)  
**Target:** 9+/10  
**Earliest achievable:** 3–4 sprints of dedicated architecture work (~6–8 weeks with 1–2 engineers)  
**Governing principle:** Every change must be reversible in isolation. Every WP must pass `test_architecture_fitness.py` before merging.

---

## Score Breakdown — What Must Change

| Criterion | Current | Target | Gap |
|---|---|---|---|
| Layers correctly separated | 6/10 — 13 lazy infra leaks, services↔flows cycle | 9/10 — zero module-level leaks, cycle broken | 3 WPs |
| Patterns consistent | 5/10 — DI + singletons mixed, god modules | 9/10 — DI-first, no god files | 3 WPs |
| Observable | 5/10 — metrics exist but no structured tracing | 8/10 — structured audit trail, telemetry | 1 WP |
| Testable | 6/10 — architecture tests exist, but cycle prevents isolation | 9/10 — flows and services independently testable | 1 WP |
| Scalable | 5/10 — single-process SQLite, _emit() bottleneck | 8/10 — non-blocking event pipeline, bounded concurrency | 2 WPs |

---

## Work Packages

### WP-0: Architecture Test Gate (prerequisite)

**Effort:** 0.5 sprint  
**Depends on:** Nothing  
**Blocks:** WP-1 through WP-8

**What:** Strengthen the architecture fitness test suite so every WP has a measurable gate.

**Steps:**
1. `tests/unit/test_architecture_fitness.py` — add test `test_application_services_no_infra_imports` that scans `weebot/application/services/*.py` and asserts zero `from weebot.infrastructure` at *any* scope (not just module-level — the current test only catches top-level)
2. Add test `test_no_services_flows_cycle` that uses AST to verify `services/` and `flows/` have no mutual import edges
3. Add test `test_core_no_global_singletons_outside_di` that scans `core/` for `global` keyword and flags any file not on an explicit allowlist
4. Add `test_god_modules_under_800_lines` that asserts no `.py` file in `weebot/application/` exceeds 800 lines (with an allowlist of pre-existing files that shrink over time)
5. Add `test_orphan_ports_flagged` that asserts every class/protocol in `application/ports/` has at least one import or registration in `infrastructure/` or `di/`

**Verification:** New tests pass on current codebase (they should fail), then each WP removes failures incrementally.

---

### WP-1: Break the Services ↔ Flows Circular Dependency

**Effort:** 1 sprint  
**Depends on:** WP-0  
**Score contribution:** +1.0 (layers + testability)  
**Risk:** MEDIUM — many import paths to update

**What:** Create `weebot/application/abstractions/` to hold cross-package interfaces. Services depend on abstractions. Flows depend on services. Neither imports the other at package level.

**Steps:**

1. **Extract `BaseFlow` interface** — Move `class BaseFlow` from `weebot/application/flows/base_flow.py` to `weebot/application/abstractions/base_flow.py`. The original file becomes a re-export for backward compatibility with a deprecation warning.
   ```
   weebot/application/abstractions/base_flow.py  (new)
   weebot/application/abstractions/__init__.py   (new)
   ```

2. **Create flow registry** — `weebot/application/abstractions/flow_registry.py`:
   ```python
   class FlowRegistry:
       """Registry of flow factories keyed by flow type string."""
       _factories: dict[str, Callable[..., BaseFlow]] = {}
       def register(self, name: str, factory: Callable): ...
       def create(self, name: str, **kwargs) -> BaseFlow: ...
   ```
   This replaces `create_flow(flow_type="plan_act", ...)` in `weebot/interfaces/factories.py`.

3. **Refactor `task_runner.py`** — Replace `from weebot.application.flows.base_flow import BaseFlow` → `from weebot.application.abstractions.base_flow import BaseFlow`. It no longer imports from `flows/` at all.

4. **Refactor `plan_act_flow.py` and state files** — Replace service imports with abstraction imports where possible. For services that have no abstraction (e.g., `memory_compactor`, `context_switcher`), create lightweight Protocols in `abstractions/` or accept them as injected constructor dependencies.

5. **Register flows in DI** — `configure_defaults()` registers `PlanActFlow` factory in `FlowRegistry`. Entry points use `container.get(FlowRegistry).create("plan_act", ...)` instead of direct `create_flow()`.

**Files touched:**
- NEW: `weebot/application/abstractions/base_flow.py`
- NEW: `weebot/application/abstractions/flow_registry.py`
- NEW: `weebot/application/abstractions/__init__.py`
- MODIFIED: `weebot/application/services/task_runner.py`
- MODIFIED: `weebot/application/flows/base_flow.py` (re-export shim)
- MODIFIED: `weebot/application/flows/plan_act_flow.py`
- MODIFIED: `weebot/application/flows/states/completed.py`, `verifying.py`, etc.
- MODIFIED: `weebot/interfaces/factories.py`
- MODIFIED: `weebot/application/di/__init__.py`

**Verification:**
```bash
python -m pytest tests/unit/test_architecture_fitness.py::test_no_services_flows_cycle
python -m pytest tests/unit/test_architecture_fitness.py  # all 19+ pass
python -m pytest tests/unit/test_plan_act_flow.py         # existing flow tests pass
```

---

### WP-2: Deflate the God Modules

**Effort:** 1.5 sprints  
**Depends on:** WP-1 (needs the cycle broken before splitting plan_act_flow)  
**Score contribution:** +1.0 (pattern consistency + maintainability)  
**Risk:** HIGH for `_call_with_cascade()` — this is the hot path

**What:** Split `model_selection.py` (3,265 lines) and `executor/_base.py` (1,400 lines, 650-line god method) into focused modules.

**Steps:**

**2a. Split `model_selection.py`** (LOW risk — pure data reorg)

1. Create `weebot/config/model_registry/` directory:
   ```
   weebot/config/model_registry/__init__.py        # re-exports
   weebot/config/model_registry/_models.py          # MODEL_CASCADE_TIER1..4, MODEL_DI_DEFAULT
   weebot/config/model_registry/_roles.py           # ROLE_MODEL_CONFIG, role mappings
   weebot/config/model_registry/_costs.py           # cost-per-token tables
   weebot/config/model_registry/_providers.py       # provider endpoint configs
   weebot/config/model_registry/_capabilities.py    # vision, tool-use support matrices
   ```
2. `model_selection.py` becomes a re-export module (50 lines) with deprecation warning.
3. Update ~15 files that import from `model_selection` to use the new paths.

**2b. Extract cascade strategies from `_call_with_cascade()`** (HIGH risk)

1. Create `weebot/application/strategies/cascade.py`:
   ```python
   class CascadeStrategy(ABC):
       """Encapsulates a model cascade dispatch strategy."""
       @abstractmethod
       async def execute(self, messages, tools, **kwargs) -> LLMResponse: ...

   class ParallelProbeCascade(CascadeStrategy):
       """Fire N models concurrently, return first success."""
       def __init__(self, probes: list[str], timeout: float, semaphore: Semaphore): ...

   class SequentialFallbackCascade(CascadeStrategy):
       """Try models in order with per-model timeout."""
       def __init__(self, chain: list[str], timeout_per: float): ...

   class RescueCascade(CascadeStrategy):
       """Fall through to live OpenRouter model discovery as last resort."""

   class CompositeCascade(CascadeStrategy):
       """Combine strategies: parallel probes → sequential → rescue."""
   ```

2. Extract error classification from `_call_with_cascade()` into `weebot/application/strategies/error_policy.py`:
   ```python
   class ErrorPolicy:
       def classify(self, error: Exception) -> ErrorClass: ...
       def should_retry(self, error_class: ErrorClass, attempt: int) -> bool: ...
       def should_fallback(self, error_class: ErrorClass) -> bool: ...
   ```

3. Extract circuit-breaker into `weebot/application/strategies/circuit_breaker.py` (wrap the existing `core/circuit_breaker.py` with an application-layer abstraction that's DI-injectable).

4. Wire the strategies in `ExecutorAgent.__init__()` via DI:
   ```python
   self._cascade = container.get(CascadeStrategy)  # injected
   self._error_policy = container.get(ErrorPolicy)  # injected
   ```

5. `_call_with_cascade()` becomes a thin orchestrator (~100 lines):
   ```python
   async def _call_with_cascade(self, messages, tools, **kwargs) -> LLMResponse:
       return await self._cascade.execute(messages, tools, **kwargs)
   ```

**Files touched:**
- NEW: `weebot/config/model_registry/` (5 files)
- NEW: `weebot/application/strategies/cascade.py`
- NEW: `weebot/application/strategies/error_policy.py`
- NEW: `weebot/application/strategies/circuit_breaker.py`
- NEW: `weebot/application/strategies/__init__.py`
- MODIFIED: `weebot/config/model_selection.py` → re-export shim
- MODIFIED: `weebot/application/agents/executor/_base.py` → thin orchestrator
- MODIFIED: `weebot/application/di/__init__.py`
- MODIFIED: ~15 importers of `model_selection`

**Verification:**
```bash
# No file in application/ exceeds 800 lines
python -m pytest tests/unit/test_architecture_fitness.py::test_god_modules_under_800_lines

# Cascade strategies are independently testable
python -m pytest tests/unit/test_cascade_strategies.py
python -m pytest tests/unit/test_error_policy.py

# No regression on executor behavior
python -m pytest tests/unit/test_executor_agent.py
python -m pytest tests/integration/test_integration_plan_act.py
```

---

### WP-3: Eliminate Layer Leaks (13 Lazy Infra Imports)

**Effort:** 0.5 sprint  
**Depends on:** WP-1 (services need abstractions to receive infra references)  
**Score contribution:** +0.5 (layer separation)  
**Risk:** LOW — all are lazy imports, conversion to DI injection is mechanical

**What:** Convert all 13 lazy `from weebot.infrastructure` imports in `application/services/` to DI-injected dependencies.

**Steps:**

For each of the 13 violations, apply this pattern:

| File | Current (lazy import) | Fix |
|---|---|---|
| `services/autonomous_learning.py` | `from weebot.infrastructure.persistence.skill_store import SkillStore` | Accept `skill_store` in `__init__`, inject via DI |
| `services/meta_self_improver.py` | `from weebot.infrastructure.persistence.meta_improvement_log import MetaImprovementLog` | Accept `meta_log` in `__init__` |
| `services/model_selection.py` | `from weebot.infrastructure.adapters.llm.adapter_factory import create_adapter` | Already DI-injected via LLMPort |
| `services/multi_source_research.py` | `from weebot.infrastructure.external_service_integration import ServiceRegistry` | Inject `ServiceRegistry` in `__init__` |
| `services/strategy_transfer.py` | `from weebot.infrastructure.persistence.strategy_store import StrategyStore` | Inject in `__init__` |
| `services/task_runner.py` | `from weebot.infrastructure.observability import metrics` | Accept `metrics` port in `__init__` |
| `flows/harness_opt_flow.py` | `from weebot.infrastructure.persistence.trajectory_repo` | Inject in constructor |
| `flows/plan_act_flow.py` | `from weebot.infrastructure.observability import metrics` | Inject via `__init__` |
| `flows/skill_opt_flow.py` | `SkillStore`, `TrajectoryRepository` | Inject in constructor |
| `agents/executor/_base.py` | `_multimodal` imports | Inject `MultimodalPort` |
| `agents/executor/_base.py` | `build_image_message` | Inject `MultimodalPort` |

**Pattern — before:**
```python
async def some_method(self):
    from weebot.infrastructure.whatever import Something
    result = Something.do_thing()
```

**Pattern — after:**
```python
def __init__(self, something: SomethingPort = None):
    self._something = something

async def some_method(self):
    result = self._something.do_thing()
```

For services that are constructed without DI today (e.g., inside state files), add a factory method to the DI container.

**Verification:**
```bash
# Must pass: zero infra imports in application/services
python -m pytest tests/unit/test_architecture_fitness.py::test_application_services_no_infra_imports
```

---

### WP-4: Event Pipeline Middleware — Fix the _emit() Bottleneck

**Effort:** 1 sprint  
**Depends on:** WP-1 (needs abstractions package for middleware interface)  
**Score contribution:** +1.0 (scalability + testability + observability)  
**Risk:** MEDIUM — changes the hot path for all event processing

**What:** Refactor `PlanActFlow._emit()` into a composable middleware chain. Each middleware is independently testable. DB persistence moves to a background task.

**Steps:**

1. **Define middleware interface** — `weebot/application/middleware/event_middleware.py`:
   ```python
   class EventMiddleware(ABC):
       """Processes an event before it reaches session/event-bus/persistence."""
       @abstractmethod
       async def process(self, event: AgentEvent, context: dict) -> AgentEvent: ...
   ```

2. **Extract existing _emit() stages into middleware classes:**
   - `TruthBindingMiddleware` — the truth-binding check (currently lines 248-275)
   - `CredentialSanitizerMiddleware` — credential redaction (currently lines 277-284)
   - `SessionMutationMiddleware` — `self._session = self._session.add_event(event)` (line 287)
   - `EventBusPublishMiddleware` — publish to event bus + domain events (lines 290-296)
   - `PersistenceMiddleware` — DB persistence with retry + dead-letter (lines 300-315)

3. **Create middleware chain** — `weebot/application/middleware/chain.py`:
   ```python
   class EventPipeline:
       def __init__(self, middlewares: list[EventMiddleware]):
           self._chain = middlewares

       async def process(self, event: AgentEvent, context: dict) -> AgentEvent:
           for mw in self._chain:
               event = await mw.process(event, context)
           return event
   ```

4. **Move DB persistence to background** — `PersistenceMiddleware` fires-and-forgets:
   ```python
   async def process(self, event, context):
       session = context["session"]
       asyncio.ensure_future(self._persist(session))
       return event
   ```

5. **`_emit()` becomes:**
   ```python
   async def _emit(self, event: AgentEvent) -> None:
       context = {"session": self._session, "flow": self, "facts": self._session.get_facts()}
       event = await self._event_pipeline.process(event, context)
       # Session mutation happens inside a middleware, so re-sync
       self._session = context["session"]
   ```

6. **Register pipeline in DI** — `configure_defaults()` builds `EventPipeline` with all middlewares.

**Files touched:**
- NEW: `weebot/application/middleware/event_middleware.py`
- NEW: `weebot/application/middleware/chain.py`
- NEW: `weebot/application/middleware/middlewares/truth_binding.py`
- NEW: `weebot/application/middleware/middlewares/credential_sanitizer.py`
- NEW: `weebot/application/middleware/middlewares/session_mutation.py`
- NEW: `weebot/application/middleware/middlewares/event_bus_publish.py`
- NEW: `weebot/application/middleware/middlewares/persistence.py`
- MODIFIED: `weebot/application/flows/plan_act_flow.py` (shrink `_emit()`)
- MODIFIED: `weebot/application/di/__init__.py`

**Verification:**
```bash
# Each middleware is independently testable
python -m pytest tests/unit/test_truth_binding_middleware.py
python -m pytest tests/unit/test_credential_sanitizer_middleware.py
python -m pytest tests/unit/test_event_pipeline.py

# Flow behavior unchanged
python -m pytest tests/unit/test_plan_act_flow.py
python -m pytest tests/integration/test_integration_plan_act.py

# No performance regression — pipeline overhead < 1ms
python -m pytest tests/unit/test_architecture_fitness.py
```

---

### WP-5: DI Container — Migrate Core Singletons

**Effort:** 1 sprint  
**Depends on:** WP-1 (container must support new abstractions)  
**Score contribution:** +0.5 (pattern consistency + testability)  
**Risk:** LOW per singleton — additive changes

**What:** Migrate 10 core singletons to DI-managed services. Leave process-level resources (browser, DB connection pools) at module scope.

**Migration candidates (in priority order):**

| Singleton | File | Migration |
|---|---|---|
| `SafetyChecker._llm_instance` | `core/safety.py:19` | DI-register `SafetyCheckerPort` → accept `LLMPort` in constructor |
| `_global_handler` | `core/error_system_handler.py:152` | DI-register `ErrorHandlerPort` |
| `_global_monitor` | `core/memory_monitor.py:387` | DI-register `MemoryMonitorPort` |
| `_default_manager` | `core/alerting.py:319` | DI-register `AlertingPort` |
| `_global_hitl_service` | `domain/services/human_interaction.py:50` | Move to DI as `HumanInteractionPort` |
| `_tracker_registry` | `core/behavior_tracker.py:485` | DI-register `BehaviorTrackerPort` |
| `default_approval_manager` | `core/approval.py:280` | DI-register `ApprovalPort` |
| `_analyzer` (bash) | `tools/bash_security.py:442` | DI-register `CommandSecurityPort` |
| `_scheduler` (schedule tool) | `tools/schedule_tool.py:18` | DI-register `SchedulingPort` |
| `_validation_pipeline` | `tools/validation.py:244` | DI-register `ValidationPort` |

**Pattern — before:**
```python
# core/safety.py
class SafetyChecker:
    _llm_instance = None
    def __init__(self):
        if SafetyChecker._llm_instance is None:
            SafetyChecker._llm_instance = ChatOpenAI(...)  # module global
```

**Pattern — after:**
```python
# application/ports/safety_port.py
class ISafetyChecker(Protocol):
    def is_critical_operation(self, action: str, tool: str) -> bool: ...
    async def generate_plan_b(self, action: str, context: str) -> dict: ...

# core/safety.py
class SafetyChecker(ISafetyChecker):
    def __init__(self, llm: LLMPort):
        self._llm = llm  # injected, not global

# DI registration
container.register(ISafetyChecker, lambda: SafetyChecker(container.get(LLMPort)))
```

**Verification:**
```bash
# Core singletons decreasing
python -m pytest tests/unit/test_architecture_fitness.py::test_core_no_global_singletons_outside_di

# Each migrated service has a unit test with mock injection
python -m pytest tests/unit/test_safety_checker.py
python -m pytest tests/unit/test_error_handler.py
# ... (one new test per migration)
```

---

### WP-6: Port Rationalization — Collapse Orphan Abstractions

**Effort:** 0.5 sprint  
**Depends on:** WP-5 (singletons migrated, so port landscape is clearer)  
**Score contribution:** +0.5 (pattern consistency — reduces premature abstraction)  
**Risk:** LOW — removing dead code

**What:** Audit all 55+ ports. Keep DI-boundary ports (LLM, StateRepository, Sandbox, EventBus, Metrics). Demote or remove single-implementation ports that add indirection without value.

**Action matrix:**

| Category | Count | Action |
|---|---|---|
| **DI-boundary ports** (LLMPort, StateRepositoryPort, SandboxPort, EventBusPort, MetricsPort, ...) | ~15 | Keep — these are the architectural boundaries |
| **Single-impl ports with no abstraction value** (CheckpointPort, ConfigPort, SoulProviderPort, SpeechPort, ...) | ~20 | Demote — replace with direct service classes. Keep the interface only if a second implementation is planned. |
| **Zero-impl ports** (CapabilityGatePort, TruthBindingPort) | 2 | Delete — dead code. |
| **Multi-impl ports** (ToolRepositoryPort, RerankPort, ...) | ~18 | Keep — abstraction is justified. |

**Steps:**
1. For each port to demote: move the interface into the same file as its implementation. Delete the separate port file.
2. Update DI registration to bind the concrete class directly (no interface).
3. For zero-impl ports: delete the file. Remove any references.
4. Update `test_architecture_fitness.py::test_ports_have_adapters` to reflect new counts.

**Verification:**
```bash
python -m pytest tests/unit/test_architecture_fitness.py::test_ports_have_adapters
python -m pytest tests/unit/test_architecture_fitness.py::test_orphan_ports_flagged
```

---

### WP-7: Observability — Structured Audit Trail + Telemetry

**Effort:** 0.5 sprint  
**Depends on:** WP-4 (middleware pipeline exists; audit middleware plugs in)  
**Score contribution:** +0.5 (observability)  
**Risk:** LOW — additive

**What:** Integrate the existing `AuditLog` into the event pipeline and add structured telemetry to the cascade dispatcher.

**Steps:**

1. **Audit middleware** — `weebot/application/middleware/middlewares/audit.py`:
   ```python
   class AuditMiddleware(EventMiddleware):
       def __init__(self, audit_log: AuditLog):
           self._log = audit_log
       async def process(self, event, context):
           await self._log.record(event.type, {"event": event.model_dump()})
           return event
   ```

2. **Cascade telemetry** — Add to `CompositeCascade` (from WP-2):
   ```python
   async def execute(self, messages, tools, **kwargs) -> LLMResponse:
       start = time.monotonic()
       result = await self._inner.execute(messages, tools, **kwargs)
       elapsed = time.monotonic() - start
       self._telemetry.record_cascade(
           model=result.model,
           probes_attempted=self._attempts,
           latency_ms=elapsed * 1000,
       )
       return result
   ```

3. **Health endpoint** — `weebot/interfaces/web/routers/health.py` (already exists) — add cascade success-rate and DB connection pool stats.

4. **Prometheus metrics** — Add gauges:
   - `flow_events_processed_total` (counter)
   - `cascade_success_rate` (gauge, per model)
   - `db_write_latency_ms` (histogram)
   - `event_pipeline_latency_ms` (histogram)

**Verification:**
```bash
curl http://localhost:8000/metrics | grep weebot_cascade
curl http://localhost:8000/api/health | jq .components.cascade
```

---

### WP-8: Scalability — Bounded Concurrency + Session Isolation

**Effort:** 1 sprint  
**Depends on:** WP-2 (cascade strategies extracted; can add bounds)  
**Score contribution:** +0.5 (scalability)  
**Risk:** MEDIUM — changes concurrency model

**What:** Add global LLM concurrency bounds, session-level DB isolation, and per-session rate limiting.

**Steps:**

1. **Global LLM semaphore** — `weebot/application/strategies/llm_pool.py`:
   ```python
   class LLMPool:
       """Bounded pool for concurrent LLM calls across all sessions."""
       def __init__(self, max_concurrent: int = 12):
           self._semaphore = asyncio.Semaphore(max_concurrent)
       async def acquire(self) -> None: ...
       def release(self) -> None: ...
   ```
   Every LLM adapter acquires from this pool before making API calls. The semaphore ensures the process never has >12 concurrent API requests.

2. **Session store isolation** — `StateRepositoryPort` gets a `with_session(session_id)` context manager that pins the DB connection to a single session, preventing cross-session lock contention.

3. **Per-session rate limiter** — `weebot/application/services/session_rate_limiter.py`:
   ```python
   class SessionRateLimiter:
       def __init__(self, max_tool_calls_per_minute: int = 30):
           self._buckets: dict[str, TokenBucket] = {}
       async def check(self, session_id: str) -> bool: ...
   ```

4. **Configurable via settings:**
   ```python
   # weebot/config/settings.py additions
   llm_max_concurrent_requests: int = 12
   session_max_tool_calls_per_minute: int = 30
   session_rate_limiting_enabled: bool = True
   ```

**Verification:**
```bash
# Load test: 20 concurrent sessions, 0 LLM calls exceed semaphore
python -m pytest tests/integration/test_concurrency.py -k test_llm_semaphore_bounds

# Architecture tests still pass
python -m pytest tests/unit/test_architecture_fitness.py
```

---

## Dependency Graph

```
WP-0 (test gate)
  │
  ├──► WP-1 (break services↔flows cycle) ───────┐
  │     │                                        │
  │     ├──► WP-2 (god modules) ────────────────┤
  │     │     │                                  │
  │     │     └──► WP-3 (layer leaks) ──────────┤
  │     │                                        │
  │     ├──► WP-4 (event pipeline) ─────────────┤
  │     │     │                                  │
  │     │     └──► WP-7 (observability) ────────┤
  │     │                                        │
  │     └──► WP-5 (core singletons → DI) ───────┤
  │           │                                  │
  │           └──► WP-6 (port rationalization) ──┤
  │                                              │
  └──► WP-8 (scalability bounds) ───────────────┘
```

**Critical path:** WP-0 → WP-1 → WP-2 → WP-8 (4 sprints minimum)  
**Parallelizable:** WP-5 + WP-6 can run alongside WP-3 + WP-4 (different files)

---

## Score Trajectory

| Milestone | WPs Completed | Estimated Score | Key Improvement |
|---|---|---|---|
| Baseline | — | 6/10 | — |
| After WP-1 | 0, 1 | 7/10 | Cycle broken, flows/services independently testable |
| After WP-2 | 0, 1, 2 | 7.5/10 | God modules deflated, cascade testable |
| After WP-3 | 0, 1, 2, 3 | 8/10 | Zero infra leaks in application layer |
| After WP-4 | 0, 1, 2, 3, 4 | 8.5/10 | Event pipeline middleware, non-blocking persistence |
| After WP-5 | 0, 1, 2, 3, 4, 5 | 9/10 | Core singletons migrated to DI |
| After WP-6 | 0, 1, 2, 3, 4, 5, 6 | 9/10 | Orphan ports removed, pattern consistency |
| After WP-7 | 0, 1, 2, 3, 4, 5, 6, 7 | 9/10 | Full observability |
| After WP-8 | 0, 1, 2, 3, 4, 5, 6, 7, 8 | **9.5/10** | Scalability bounds, rate limiting |

**Why 9.5 not 10:** The last 0.5 would come from:
- Multi-process session isolation (out of scope for single-process Python)
- Full PostgreSQL migration with read replicas (infrastructure, not architecture)
- These are deployment architecture concerns, not code architecture

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| WP-2 cascade refactor breaks hot path | Medium | High | Full integration test coverage before touching cascade. Run 100+ E2E flows against staging. |
| WP-1 import refactor causes circular imports | Medium | Medium | Do one file at a time. Architecture test catches cycles immediately. |
| WP-4 pipeline overhead degrades performance | Low | Medium | Benchmark before/after. Pipeline is a list iteration — sub-millisecond. |
| WP-5 singleton migration breaks implicit contracts | Medium | Low | Migrate one singleton per PR. Each has its own test. |
| WP-8 semaphore causes deadlocks under load | Low | Medium | Use `asyncio.wait_for` on all semaphore acquires. Test with 10× load in integration. |

---

## Merge Checklist (per WP)

- [ ] `pytest tests/unit/test_architecture_fitness.py` — all tests pass
- [ ] `pytest tests/unit/` — no regressions in unit tests
- [ ] `pytest tests/integration/` — no regressions in integration tests
- [ ] `python -m cli.main flow run "test"` — smoke test (CLI entry point works)
- [ ] `python -m cli.main health` — health check passes
- [ ] No new `global` keywords in `weebot/application/` or `weebot/domain/`
- [ ] No new `from weebot.infrastructure` in `weebot/application/services/`
- [ ] PR description links to the WP section in this document
