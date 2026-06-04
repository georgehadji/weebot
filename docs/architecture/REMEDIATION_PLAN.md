# Architectural Remediation Plan: 5.5 → 9.0+

**Status:** Approved — In Progress  
**Author:** Architecture Audit  
**Date:** 2026-07-06  
**Target Score:** > 9/10  

## Scoring Rubric

| Dimension | Current | Target | Gain |
|---|---|---|---|
| Architecture Fidelity | 6/10 | 10/10 | Enforce all layer boundaries with AST-based import tests |
| Dependency Direction | 5/10 | 10/10 | Zero cross-layer violations from tools/infra/interfaces to wrong layers |
| Modular Cohesion | 7/10 | 9/10 | Split user_profile.py; pure ABC ports; pydantic-light domain |
| Testing Architecture | 4/10 | 9/10 | Mirror-structured tests; 80%+ coverage; property-based testing |
| Observability | 5/10 | 9/10 | Wire structured logging, alerting, telemetry, domain events |
| Concurrency Safety | 7/10 | 9/10 | Remove threading.Lock in async code; multi-worker SQLite safety |
| Error Handling | 3/10 | 9/10 | Unified WeebotError hierarchy; typed error events; mediator preserves types |
| Extensibility | 5/10 | 9/10 | Zero bypassed ports; DI-only injection; no fallback-to-concrete |
| Configuration | 4/10 | 9/10 | ConfigService port; no global singletons; full schema validation |

## Phase Sequencing

Each phase depends on the previous one completing cleanly:

```
Phase 1 (Foundation) ──► Phase 2 (Renovation) ──► Phase 3 (Unification) ──► Phase 4 (Hardening)
    1-2 days                 1 week                    2 weeks                   2-3 weeks
```

## Phase 1 — Foundation: Fix Critical Bugs & Restore Core Purity

### step-1: Register 5 dead CQRS command/handler pairs in mediator
**Target:** `weebot/application/cqrs/handlers.py`  
**Action:** Add `register_command_handler()` calls for `ApplySkillEditsCommand`, `ScoreTrajectoryCommand`, `BuildOptimizationBatchCommand`, `ValidateSkillCommand`, `ValidateTransferCommand` in `register_default_handlers()` or a dedicated `register_skillopt_handlers()` called from the DI container when building `SkillOptFlow`.  
**Acceptance:** All 13 command types registered; `mediator.send()` for each succeeds without `HandlerNotRegisteredError`.

### step-2: Fix 3 broken `from .ai_router import TaskType` imports
**Target:** `weebot/infrastructure/adapters/gitnexus_provider.py`, `gitnexus_router.py`, `rtk_ai_router.py`  
**Action:** Define `TaskType` in `domain/models/task_type.py` and have both infrastructure adapters and application services import from domain.  
**Acceptance:** Import succeeds; no `ModuleNotFoundError` at runtime.

### step-3: Fix health.py undefined variable references
**Target:** `weebot/interfaces/web/routers/health.py`  
**Action:** Inject `StateRepositoryPort` and connection pool stats through DI container or request-scoped dependencies.  
**Acceptance:** `/health` endpoint returns 200 without `NameError`.

### step-4: Fix core/errors.py reverse dependency on infrastructure/security
**Target:** `weebot/domain/exceptions.py`, `weebot/core/errors.py`, `weebot/infrastructure/security/security_validators.py`  
**Action:** Move security error classes into `domain/exceptions.py`; update all importers to reference from domain.  
**Acceptance:** `core/errors.py` has zero infra imports; domain is single source for all error classes.

### step-5: Fix core/agent_context.py reverse dependency on application ports
**Target:** `weebot/core/agent_context.py`, `weebot/application/di.py`  
**Action:** Define lightweight `StateProvider` protocol in core; application DI supplies adapter; remove import of application port from core.  
**Acceptance:** Core imports zero application modules.

### step-6: Split user_profile.py into domain/application/infrastructure files
**Target:** `weebot/domain/models/user_profile.py`  
**Action:** Extract domain models, create `ProfileStoragePort` ABC, move concrete storage adapters to infrastructure, move `UserProfileManager` to `application/services`.  
**Acceptance:** `domain/models/user_profile.py` ≤ 200 lines; storage adapters in infrastructure; manager in application.

## Phase 2 — Renovation: Remove Direct Cross-Layer Coupling

### step-7: Remove all 14 infrastructure bypasses from tools layer
**Target:** 11 tool files + `di.py` + `factories.py`  
**Action:** Make port dependencies required constructor args; remove fallback-to-concrete patterns; update `tool_registry`/`factories` to inject via DI.  
**Acceptance:** Zero tools import from `weebot.infrastructure`; all adapters injected via constructor.

### step-8: Remove all 25 interface→infrastructure/core/tools bypasses
**Target:** 10 interface files  
**Action:** Replace direct infrastructure/core/tools imports with application port types; wire concretions through DI; use FastAPI `Depends` for injection.  
**Acceptance:** Architecture test confirms interfaces layer imports zero infra/core/tools modules.

### step-9: Remove concrete logic from application ports
**Target:** `notification_port.py`, `sandbox_port.py`, `browser_port.py`, `optimizer_port.py`, `llm_port.py`  
**Action:** Extract `NotificationBus` to infrastructure; extract `SandboxPort` defaults to adapter base; extract `BrowserPort` context manager to mixin; extract `LLMResponse` to domain models.  
**Acceptance:** Every application port is a pure ABC with only `@abstractmethod` declarations; zero concrete methods.

### step-10: Add ConfigService with ConfigPort to unify configuration
**Target:** `weebot/application/ports/config_port.py`, `weebot/infrastructure/adapters/config_adapter.py`  
**Action:** Create `ConfigPort(ABC)` in application/ports; create `ConfigAdapter` wrapping `WeebotSettings`+constants in infrastructure; migrate all direct config imports to constructor injection.  
**Acceptance:** At least 80% of config consumers use `ConfigPort` injection; zero new direct config imports.

## Phase 3 — Unification: Error, Observability & Event Architecture

### step-11: Unify error hierarchy under domain/exceptions.py WeebotError
**Target:** 6 files across all layers  
**Action:** All exception classes inherit from domain `WeebotError`; mediator preserves exception objects in `CommandResult`; `ErrorEvent` carries typed error; wire `ErrorHandler` decorators into adapters.  
**Acceptance:** Single `WeebotError` root; mediator preserves exception type; `ErrorEvent.error` is reconstructable exception.

### step-12: Wire orphaned observability components
**Target:** 5 files  
**Action:** Wire `StructuredLogger` into flows/agents/services; register `AlertManager` in DI; register `TelemetryBehavior` in mediator pipeline; add `flow_step_duration_seconds` observe calls.  
**Acceptance:** All flows use `StructuredLogger`; mediator pipeline includes `TelemetryBehavior`; `flow_step_duration_seconds` is non-zero at runtime.

### step-13: Publish domain events through event bus
**Target:** `event_bus_port.py`, planning/executing states, `event_store.py`  
**Action:** Extend `EventBusPort` with domain event types; `PlanActFlow` yields domain events alongside `AgentEvent`; `EventStore` persists domain events.  
**Acceptance:** Domain events (`PlanCreated`, `StepStarted`, `StepCompleted`, `FactDiscovered`) are published and persisted.

## Phase 4 — Hardening: Testing, Legacy Removal & Coverage

### step-14: Restructure test suite to mirror source architecture
**Target:** `tests/unit/`  
**Action:** Create layer-matched subdirectories; move flat test files; add per-layer `conftest.py` with shared fixtures.  
**Acceptance:** Test directory tree mirrors `weebot/` source tree; zero tests in flat `tests/unit/`.

### step-15: Add coverage tracking with 80% threshold
**Target:** `.coveragerc`, `architecture.yml`  
**Action:** Add per-layer thresholds; add `--cov-fail-under=80` to CI.  
**Acceptance:** CI fails under 80% coverage.

### step-16: Add property-based tests and extend architecture contracts
**Target:** 3 new test files  
**Action:** Add `hypothesis` for state transitions; extend `test_architecture_fitness.py` to enforce ALL dependency contracts; add CQRS registration test.  
**Acceptance:** State machine + event round-trips tested via hypothesis; architecture test verifies all 5 importlinter contracts; CQRS registration test passes.

### step-17: Remove legacy modules
**Target:** `agent_core_v2.py`, `state_manager.py`, `state_coordinator.py`, `weebot/__init__.py`  
**Action:** Migrate remaining consumers; delete legacy modules; clean up top-level re-exports.  
**Acceptance:** Zero imports of removed modules; `weebot/__init__.py` lazy map cleaned.

## Risk Matrix

| Phase | Risk Level | Key Risk | Mitigation |
|---|---|---|---|
| 1 — Foundation | Low-Medium | API breakage from security error migration | Deprecation path: old imports still work via re-export for one cycle |
| 2 — Renovation | Medium | 25 interface files changing; CI may fail on import tests | Work layer-by-layer; commit between layers; run architecture tests after each |
| 3 — Unification | High | Error hierarchy change touches every exception raise/catch | Use grep to find all `raise` + `except` sites; automated refactoring tool |
| 4 — Hardening | Low | Test moves may break CI if imports reference relative paths | Run full test suite after each move |

## Verification

After each step:
1. Run `pytest tests/ -v --tb=short -x` — all tests pass
2. Run `python -m cli.main health` — app boots
3. Architecture test: `pytest tests/unit/test_architecture_fitness.py -v -x` — all contracts pass

After Phase 2 completion:
4. Import linter: `lint-imports` — zero violations

After Phase 4 completion:
5. Coverage: `pytest --cov=weebot --cov-fail-under=80` — threshold met
