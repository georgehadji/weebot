# Architecture Remediation Plan — Weebot v2.8 → v3.0

**Derived from:** June 2026 Architectural Audit  
**Baseline:** May 2026 Forensic Reconstruction (Enhancements 1–10)  
**Audit score:** 4 CRITICAL · 8 HIGH · 12 MEDIUM · 7 LOW findings  
**Target:** All CRITICAL + HIGH findings resolved, all MEDIUM at minimum mitigated  
**Total effort:** ~34 person-days across 10 weeks  

---

## Table of Contents

1. [Current State Summary](#1-current-state-summary)
2. [Phase 1: Stabilize (Weeks 1–2) — Complete Partially-Done Work](#2-phase-1-stabilize-weeks-12)
3. [Phase 2: Consolidate (Weeks 3–5) — Unify Dual Systems](#3-phase-2-consolidate-weeks-35)
4. [Phase 3: Classify (Weeks 6–7) — Flat-File Remediation](#4-phase-3-classify-weeks-67)
5. [Phase 4: Harden (Weeks 8–10) — Lock In The Architecture](#5-phase-4-harden-weeks-810)
6. [Full Sprint Schedule](#6-full-sprint-schedule)
7. [Architecture Quality Gates](#7-architecture-quality-gates)
8. [Risk Register](#8-risk-register)
9. [Success Metrics](#9-success-metrics)
10. [Appendix: File Manifest](#10-appendix-file-manifest)

---

## 1. Current State Summary

### What works well

- **Domain layer is pure** — zero imports from outer layers (verified by importlinter + manual grep)
- **CQRS mediator** is well-implemented — 14+ commands, 9 queries, pipeline behaviors
- **Web router DI** uses FastAPI `Depends` + `Container.get()` correctly
- **LLM adapters** are properly port-implementing with resilience wrappers
- **Domain models** are immutable Pydantic with `model_copy(update=…)`
- **102 SkillOpt tests** covering the optimizer pipeline

### What's broken or at risk

| # | Finding | Severity | Origin |
|---|---------|----------|--------|
| F1 | Two parallel orchestration engines (PlanActFlow + ComplexTaskExecutor) | **CRITICAL** | New audit finding |
| F2 | Four parallel state management systems | **CRITICAL** | New audit finding |
| F3 | `EventBrokerAdapter` bridges only publish, not subscribe | **HIGH** | Enhancement 2 incomplete |
| F4 | `AgentContext` still imports deprecated `StateManager` | **HIGH** | Enhancement 3 incomplete |
| F5 | `ScoringPort` defaults to noop in DI | **HIGH** | Enhancement 5 incomplete |
| F6 | `SandboxPort` unused by primary execution path | **HIGH** | Known gap, unaddressed |
| F7 | `core/` is architecturally undifferentiated (26 modules, 7 concerns) | **HIGH** | New audit finding |
| F8 | 35 flat files at `weebot/` root outside any layer | **HIGH** | Enhancement 10 (not done) |
| F9 | 4 CQRS queries have no registered handlers | **MEDIUM** | New audit finding |
| F10 | `PlanActFlow` god class (300+ lines, 6 concerns) | **MEDIUM** | New audit finding |
| F11 | `__import__()` hacks in 10 locations | **MEDIUM** | New audit finding |
| F12 | `StateCoordinator` poltergeist class | **MEDIUM** | New audit finding |
| F13 | Global singletons (`get_event_bus`, `get_state_coordinator`) | **MEDIUM** | New audit finding |
| F14 | Tools bypass ports — direct `sqlite3` imports | **MEDIUM** | Known, `.importlinter` exceptions |
| F15 | `prometheus-client` and `structlog` dependencies unused | **MEDIUM** | New audit finding |
| F16 | No web API authentication or rate limiting | **MEDIUM** | New audit finding |

---

## 2. Phase 1: Stabilize (Weeks 1–2)

**Goal:** Complete the three enhancements that were marked "done" in May 2026 but remain partially implemented. Address the highest-priority quick wins from the new audit.

### 2.1 Complete Enhancement 3 — Remove StateManager from AgentContext

**Effort:** 0.5 days  
**Dependencies:** None  
**Files modified:**

| File | Action |
|------|--------|
| `weebot/core/agent_context.py` | Replace `StateManager` param with `StateRepositoryPort`. Remove `from weebot.state_manager import StateManager`. |
| `weebot/core/agent_context_final.py` | Same — update `create_orchestrator()` signature. |
| `weebot/core/agent_context_v2.py` | Same — update `create_orchestrator()` signature. |
| `weebot/state_coordinator.py` | Replace `self.state_manager = StateManager()` with injection of `StateRepositoryPort` via constructor. |
| `weebot/mcp/server.py` | Use `LegacyProjectAdapter` for project CRUD instead of `StateManager`. |
| `weebot/mcp/resources.py` | Same — use `LegacyProjectAdapter`. |

**Verification:**
```bash
grep -rn "from weebot.state_manager import" weebot/core/ weebot/mcp/ --include="*.py"
# Expected: 0 results (imports remain only in test files and state_coordinator shim)
pytest tests/unit/test_architecture_fitness.py -v -k "state_manager"
```

### 2.2 Complete Enhancement 5 — Wire Real ScoringPort in DI

**Effort:** 0.5 days  
**Dependencies:** None  
**Files modified:**

| File | Action |
|------|--------|
| `weebot/application/di.py` | Replace `_create_default_scorer()` with `_create_scorer(harness)` that instantiates `ExactMatchScorer`, `ExecutionResultScorer`, or `VerifierScorer`. |
| `weebot/application/di.py` | Update `configure_skillopt()` to use real scorer. |

**Verification:**
```python
# In a test:
container = Container()
container.configure_skillopt()
scorer_proxy = container._maybe_get_str("validation_gate")
# Assert scorer is a real ScoringPort, not a noop lambda
```

### 2.3 Complete Enhancement 2 — Bridge EventBroker Subscriptions

**Effort:** 1 day  
**Dependencies:** None  
**Files modified:**

| File | Action |
|------|--------|
| `weebot/infrastructure/events/broker_adapter.py` | Add `subscribe()` method forwarding to `AsyncEventBus.subscribe()`. Filter by event type prefix to emulate `EventBroker.subscribe(event_type=…)`. |
| `weebot/core/agent_context.py` | Route `subscribe_to_events()` through `EventPublisher` when available; fall back to in-memory `EventBroker` only when no publisher is injected. |
| `weebot/infrastructure/event_bus.py` | Add `subscribe_by_type(event_type: str, handler)` to allow filtered subscription matching `EventBroker` semantics. |

**Verification:**
```bash
pytest tests/integration/test_event_bridge.py -v
# New integration test: publish on AsyncEventBus, receive via EventBrokerAdapter.subscribe
```

### 2.4 Register Missing CQRS Query Handlers

**Effort:** 0.5 days  
**Dependencies:** None  
**Files modified:**

| File | Action |
|------|--------|
| `weebot/application/cqrs/handlers.py` | Add `GetPlanHandler`, `GetSessionHistoryHandler`, `SearchSessionsHandler`, `GetSimilarSessionsHandler`. |
| `weebot/application/cqrs/handlers.py` | Update `register_default_handlers()` to register all 4 new handlers. |
| `weebot/application/di.py` | Update `build_mediator()` if new handlers need additional dependencies. |

**Verification:**
```python
# Fitness test:
mediator = container.build_mediator()
for query_cls in [SearchSessionsQuery, GetSimilarSessionsQuery, GetSessionHistoryQuery, GetPlanQuery]:
    assert mediator.is_query_registered(query_cls), f"{query_cls.__name__} not registered"
```

### 2.5 Document `core/` Module Classification

**Effort:** 1 day  
**Dependencies:** None  
**Output:** `docs/CORE_MODULE_CLASSIFICATION.md`

Classify all 26 `core/` modules into target layers:

| Target Layer | Modules |
|-------------|---------|
| Infrastructure | `circuit_breaker.py`, `adaptive_concurrency.py`, `memory_monitor.py`, `bash_guard.py`, `safety.py`, `approval.py`, `approval_policy.py`, `model_cascade_config.py`, `model_cascade_integration.py`, `openrouter_enhanced_cascade.py`, `openrouter_tools.py`, `behavior_tracker.py`, `behavior_integration.py`, `behavior_reporting.py`, `error_classifier.py`, `dashboard.py`, `alerting.py`, `memory_dedup.py` |
| Application | `agent.py`, `agent_context.py`, `agent_factory.py`, `agent_profile.py`, `tool_agent.py`, `workflow_orchestrator.py`, `dependency_graph.py`, `workflow_tracer.py` |

*Note:* This phase only produces the classification document. Actual moves happen in Phase 3.

**Phase 1 total effort:** 3.5 days

---

## 3. Phase 2: Consolidate (Weeks 3–5)

**Goal:** Unify the dual systems, split the god class, and wire the sandbox.

### 3.1 Extract PlanActFlow Services

**Effort:** 2 days  
**Dependencies:** Phase 1 complete  
**Files created:**

| File | Responsibility |
|------|---------------|
| `weebot/application/services/context_switcher.py` | `_maybe_switch_model_for_context()`, `_update_agents_with_model()` |
| `weebot/application/services/plan_history.py` | Undo/redo stack management (`_snapshot_plan()`, `undo()`, `redo()`) |
| `weebot/application/services/continuation_detector.py` | Short-prompt enrichment logic (`_CONTINUATION_WORDS`, `effective_prompt` resolution) |

**Files modified:**

| File | Action |
|------|--------|
| `weebot/application/flows/plan_act_flow.py` | Delegate to new services. Reduce from ~300 to ~200 lines. |
| `weebot/application/flows/states/planning.py` | Call `context_switcher` instead of flow methods. |

**Verification:**
```bash
pytest tests/unit/application/ -v -k "plan_act"
```
Target: PlanActFlow drops below 200 lines. Each new service is under 80 lines with single responsibility.

### 3.2 Deploy SandboxPort in Tools

**Effort:** 2 days  
**Dependencies:** Phase 1 complete  
**Files modified:**

| File | Action |
|------|--------|
| `weebot/tools/bash_tool.py` | Accept `SandboxPort` in constructor. Route `execute()` through sandbox. Fall back to direct execution if no sandbox configured (with warning). |
| `weebot/tools/python_tool.py` | Same — accept `SandboxPort` in constructor. |
| `weebot/tools/powershell_tool.py` | Same. |
| `weebot/application/di.py` | Wire `NativeWindowsSandbox` as default `SandboxPort` binding. |
| `weebot/tools/tool_registry.py` | Inject `SandboxPort` when creating tool collections. |

**Verification:**
```bash
# Verify tools no longer execute without sandbox involvement:
grep -n "subprocess.run\|os.system\|asyncio.create_subprocess" weebot/tools/bash_tool.py
# Expected: 0 results (all execution goes through SandboxPort)
```

### 3.3 Eliminate StateCoordinator

**Effort:** 1 day  
**Dependencies:** Phase 1.1 (StateManager removal from AgentContext)  
**Rationale:** `StateCoordinator` is a poltergeist — it delegates 100% of its behavior to `StateManager`, `AgentContext`, `ActivityStream`, and `ResponseCache` without adding logic. The DI container should wire these directly.

**Files modified:**

| File | Action |
|------|--------|
| `weebot/state_coordinator.py` | Add `DeprecationWarning`. Redirect `get_state_coordinator()` to `Container.get()`. |
| `weebot/application/di.py` | Add `ActivityStream` and `ResponseCache` as registered singletons. |
| All consumers of `StateCoordinator` | Replace with direct `Container.get()` calls or constructor injection. |
| `weebot/complex_task_executor.py` | Accept `AgentContext` factory instead of constructing `StateCoordinator`. |

**Verification:**
```bash
grep -rn "StateCoordinator\|get_state_coordinator" weebot/ --include="*.py" | grep -v "test_" | grep -v "DeprecationWarning"
# Expected: 0 results (all references migrated or deprecated)
```

### 3.4 Resolve `__import__()` Hacks

**Effort:** 1 day  
**Dependencies:** Phase 1, Phase 3.1  
**Root cause:** Circular import chains between `cqrs/handlers.py` → `cqrs/commands.py` → `tools/base.py`, and `di.py` → `mediator.py` → `handlers.py`.

**Files modified:**

| File | Current pattern | Fix |
|------|----------------|-----|
| `weebot/application/cqrs/handlers.py:33` | `_T = __import__("weebot.tools.base", ...)` | Move `ToolCollection` import into handler constructors (lazy DI). |
| `weebot/application/cqrs/handlers.py:410` | `__import__("datetime").datetime.now(...)` | Add `from datetime import datetime, timezone` at module top. |
| `weebot/application/di.py:121` | `__import__(..., fromlist=["LoggingBehavior"])` | Extract `LoggingBehavior` import path. |
| `weebot/application/di.py:145` | `__import__(..., fromlist=["register_default_handlers"])` | Use lazy registration — pass the module name and call inside `build_mediator()`. |
| `weebot/application/agents/structured_executor.py:137,149` | `__import__("json").loads(...)` | Replace with `json.loads(...)` + `import json` at module top. |
| `weebot/application/flows/skill_opt_flow.py:142` | `__import__("weebot.application.cqrs.commands.skill_edit_commands", ...)` | Import `ApplySkillEditsCommand` directly. |
| `weebot/application/flows/skill_opt_flow.py:257` | `__import__("weebot.domain.models.session", ...).Session(...)` | Import `Session` directly. |

**Verification:**
```bash
grep -rn "__import__(" weebot/application/ --include="*.py"
# Expected: 0 results
```

### 3.5 Replace Global Singletons with DI

**Effort:** 0.5 days  
**Dependencies:** Phase 1 complete  

| Singleton | Location | Fix |
|-----------|----------|-----|
| `get_event_bus()` | `weebot/infrastructure/event_bus.py` | Add `DeprecationWarning`. All consumers use `Container.get(EventBusPort)`. |
| `get_state_coordinator()` | `weebot/state_coordinator.py` | Handled by Phase 3.3. |

**Phase 2 total effort:** 6.5 days

---

## 4. Phase 3: Classify (Weeks 6–7)

**Goal:** Execute Enhancement 10 — classify and relocate all 35 flat files at `weebot/` root into correct architectural layers.

### 4.1 Bucket A — Delete Dead Code

**Effort:** 0.5 days  
**Candidates (no imports from other weebot modules, no import references from outside):**

| File | Evidence of deadness | Action |
|------|---------------------|--------|
| `weebot/source_credibility_assessment.py` | Zero cross-references found | Delete |
| `weebot/learning_from_executions.py` | Zero cross-references found | Delete (superseded by SkillOpt) |
| `weebot/customized_suggestions.py` | Zero cross-references found | Delete |
| `weebot/interface_customization.py` | Zero cross-references found | Delete |
| `weebot/intelligent_template_suggestion.py` | Zero cross-references found | Delete |
| `weebot/automatic_template_adaptation.py` | Zero cross-references found | Delete |
| `weebot/notifications_categorizer.py` | Zero cross-references found | Delete |

**Verification:** Run full test suite after each deletion. If any test breaks, the file is not dead — restore it and reclassify.

### 4.2 Bucket B — Deprecate with Shim

**Effort:** 0.5 days  

| File | Replacement | Action |
|------|-------------|--------|
| `weebot/ai_providers.py` | `infrastructure.adapters.llm.adapter_factory.create_adapter()` | Re-export `create_adapter` with `DeprecationWarning`. |
| `weebot/agent_core_v2.py` | `interfaces.cli.agent_runner.AgentRunner` | Already has `DeprecationWarning` — no change. |
| `weebot/state_manager.py` | `infrastructure.persistence.sqlite_state_repo.SQLiteStateRepository` | Already has `DeprecationWarning` — no change. |
| `weebot/ai_router.py` | `application.services.model_selection.ModelSelectionService` | Add shim + `DeprecationWarning`. |

### 4.3 Bucket C — Promote to Correct Layer

**Effort:** 2 days  

| Source | Target | Notes |
|--------|--------|-------|
| `weebot/complex_task_executor.py` | `weebot/application/services/complex_task_executor.py` | Update all 3 import sites. |
| `weebot/workflow_planner.py` | `weebot/application/flows/workflow_planner.py` | Update import sites. |
| `weebot/information_synthesis.py` | `weebot/application/services/information_synthesis.py` | |
| `weebot/multi_source_research.py` | `weebot/application/services/multi_source_research.py` | |
| `weebot/nlp_understanding.py` | `weebot/application/services/nlp_understanding.py` | |
| `weebot/strategy_adaptation.py` | `weebot/application/services/strategy_adaptation.py` | |
| `weebot/security_validators.py` | `weebot/infrastructure/security/security_validators.py` | |
| `weebot/external_service_integration.py` | `weebot/infrastructure/external_service_integration.py` | |
| `weebot/notifications.py` | `weebot/infrastructure/notifications/notifications.py` | |
| `weebot/rtk_provider.py` | `weebot/infrastructure/adapters/rtk_provider.py` | |
| `weebot/rtk_integration.py` | `weebot/infrastructure/adapters/rtk_integration.py` | |
| `weebot/rtk_ai_router.py` | `weebot/infrastructure/adapters/rtk_ai_router.py` | |
| `weebot/gitnexus_provider.py` | `weebot/infrastructure/adapters/gitnexus_provider.py` | |
| `weebot/gitnexus_router.py` | `weebot/infrastructure/adapters/gitnexus_router.py` | |
| `weebot/gitnexus_config.py` | `weebot/config/gitnexus_config.py` | |
| `weebot/activity_stream.py` | `weebot/core/activity_stream.py` | Already imported by `core/agent_context.py`. Move + update import. |
| `weebot/structured_logger.py` | `weebot/core/structured_logger.py` | |
| `weebot/error_system_base.py` | `weebot/core/error_system_base.py` | |
| `weebot/error_system_handler.py` | `weebot/core/error_system_handler.py` | |
| `weebot/error_system_user_messages.py` | `weebot/core/error_system_user_messages.py` | |
| `weebot/errors.py` | `weebot/core/errors.py` | |
| `weebot/user_profile_model.py` | `weebot/domain/models/user_profile.py` | |
| `weebot/model_registry.py` | `weebot/config/model_registry.py` | |
| `weebot/cli_support.py` | `weebot/interfaces/cli/support.py` | |

**For each move:**
1. Move the file to its new location
2. Leave a shim at the old location with `DeprecationWarning` redirecting to the new path
3. Update all internal imports
4. Run `pytest tests/ -x --tb=short` to catch import errors

### 4.4 Bucket D — Freeze

**Effort:** 0.5 days  

| File | Reason | Action |
|------|--------|--------|
| `weebot/failure_recovery.py` | Tightly coupled to `complex_task_executor.py` | Add LEGACY MODULE header. Schedule for removal when `ComplexTaskExecutor` is sunset. |
| `weebot/state_coordinator.py` | Being eliminated in Phase 3.3 | Add LEGACY MODULE header. |
| `weebot/core/agent_context.py` | Heavy coupling, being refactored in Phase 1.1 | Add LEGACY MODULE header referencing migration path. |

**Legacy module header template:**
```python
"""
⚠️ LEGACY MODULE (Bucket D — Freeze)

This module is part of the pre-Clean-Architecture legacy track.
It will not receive new features. File issues against weebot.application.*
for equivalent functionality.

Migration path: {replacement module}
Last maintainer audit: 2026-06-01
Target sunset: 2026-09-01
"""
```

### 4.5 Update `.importlinter` Contracts

**Effort:** 0.5 days  

After all moves are complete, update `.importlinter` to reflect the new reality:

```ini
[importlinter:contract:flat-file-elimination]
name = No modules may remain at weebot package root (except __init__.py and allowed shims)
type = forbidden
source_modules = weebot
source_is_package = True
forbidden_modules =
    weebot.*
allowed_source_files =
    __init__.py
    errors.py       # Shim
    state_manager.py # Shim (deprecated)
    ai_providers.py  # Shim (deprecated)
    agent_core_v2.py # Shim (deprecated)
    ai_router.py     # Shim (deprecated)
```

**Phase 3 total effort:** 4 days

---

## 5. Phase 4: Harden (Weeks 8–10)

**Goal:** Lock in the architecture with automated enforcement, observability, and security.

### 5.1 Enhance Architecture Fitness Tests

**Effort:** 1 day  
**Dependencies:** Phase 3 complete (all files in correct layers)  
**Files created:**

| File | Purpose |
|------|---------|
| `tests/unit/test_architecture_fitness.py` | 10+ AST-based tests enforcing architectural rules |

**Tests:**
1. `test_domain_has_no_outer_imports` — Domain imports nothing from core/infrastructure/interfaces/application
2. `test_application_no_module_level_infra_imports` — Application infra imports only inside TYPE_CHECKING or functions
3. `test_every_command_has_handler` — All `Command` subclasses are registered
4. `test_every_query_has_handler` — All `Query` subclasses are registered
5. `test_di_single_composition_root` — Only `di.py` creates infrastructure adapters
6. `test_no_direct_agent_calls_in_flow_states` — Flow states use `mediator.send()`
7. `test_ports_have_adapters` — Every port in `application/ports/` has a registered adapter
8. `test_no_flat_files_at_root` — Only allowed shim files at `weebot/` root
9. `test_tools_no_direct_db` — Tools use ports, not direct SQLite imports
10. `test_core_modules_in_correct_package` — `core/` modules classified per Phase 2.5 document

### 5.2 Wire Prometheus Metrics (or Remove Dependency)

**Effort:** 1 day  
**Decision point:** If metrics are needed, implement them. Otherwise, remove `prometheus-client` from `requirements.txt`.

**Option A — Implement:**
| File | Action |
|------|--------|
| `weebot/interfaces/web/main.py` | Add `/metrics` endpoint with `prometheus_client.generate_latest()`. |
| `weebot/infrastructure/observability/metrics.py` | Instrument `EventBusPort.publish()` call count, `Mediator.send()` duration histogram, `LLMPort.chat()` cost counter. |

**Option B — Remove:**
Remove `prometheus-client>=0.21.0` from `requirements.txt`. Document plan to re-add when observability strategy is finalized.

### 5.3 Add Web API Authentication Middleware

**Effort:** 1 day  
**Files modified:**

| File | Action |
|------|--------|
| `weebot/interfaces/web/main.py` | Add `AuthenticationMiddleware` (API key header or OAuth2). |
| `weebot/config/settings.py` | Add `WEEBOT_API_KEY` setting. |
| `.env.example` | Add `WEEBOT_API_KEY=` documentation. |

**Verification:**
```bash
curl -X GET http://localhost:8000/api/sessions
# Expected: 401 Unauthorized
curl -H "X-API-Key: test-key" http://localhost:8000/api/sessions
# Expected: 200 OK
```

### 5.4 Enforce Importlinter in CI

**Effort:** 0.5 days  
**Files modified:**

| File | Action |
|------|--------|
| `.github/workflows/test.yml` (or equivalent) | Add `lint-imports` job running `import-linter`. |
| `.importlinter` | Update contracts per Phase 4.5 classification. Remove legacy exceptions that have been resolved. |
| `pyproject.toml` or `Makefile` | Add `make lint-imports` target. |

### 5.5 Contract Tests Between Event Systems

**Effort:** 1 day  
**Files created:**

| File | Purpose |
|------|---------|
| `tests/integration/test_event_bridge_contract.py` | Verify `EventBrokerAdapter.publish()` → `AsyncEventBus.subscribe()` delivers correct types. |
| `tests/integration/test_event_bridge_contract.py` | Verify `EventBrokerAdapter.subscribe()` receives events from `AsyncEventBus.publish()`. |
| `tests/integration/test_event_bridge_contract.py` | Verify all known event type strings in the codebase are mapped in `EventBrokerAdapter._convert()`. |

### 5.6 Document Architecture Decisions (ADRs)

**Effort:** 1 day  
**Files created:**

| File | Decision |
|------|----------|
| `docs/adr/001-pydantic-over-dataclasses.md` | Why domain models use Pydantic `BaseModel`. |
| `docs/adr/002-mediator-over-service-layer.md` | Why CQRS with Mediator instead of Service Layer. |
| `docs/adr/003-protocol-vs-abc-ports.md` | Why domain uses Protocol, application uses ABC — or decision to unify. |
| `docs/adr/004-sqlite-over-postgres.md` | Why SQLite for a CLI-first agent framework. |
| `docs/adr/005-in-process-event-bus.md` | Why AsyncEventBus, not RabbitMQ/Kafka, for single-process deployments. |

### 5.7 Extract Shared Event Reconstruction Utility

**Effort:** 0.5 days  
**Files created:**

| File | Purpose |
|------|---------|
| `weebot/application/cqrs/event_reconstructor.py` | `reconstruct_events(event_dicts: list[dict]) -> list[AgentEvent]` using `TypeAdapter`. |

**Files modified:**

| File | Action |
|------|--------|
| `weebot/application/flows/states/planning.py` | Replace inline `TypeAdapter` usage with `reconstruct_events()`. |
| `weebot/application/flows/states/executing.py` | Same. |
| `weebot/application/flows/states/updating.py` | Same (if present). |

**Phase 4 total effort:** 6 days

---

## 6. Full Sprint Schedule

```
Week 1  ┤ Phase 1.1: StateManager→AgentContext (0.5d)
        ┤ Phase 1.2: Real ScoringPort DI     (0.5d)
        ┤ Phase 1.3: EventBroker subscription (1d)
        ┤ Phase 1.4: Missing query handlers   (0.5d)
        ┤ Phase 1.5: Core classification doc  (1d)
        ┤                                        Total: 3.5 days

Week 2  ┤ Buffer / integration testing / fix regressions
        ┤                                        Total: ~2 days

Week 3  ┤ Phase 2.1: Extract PlanActFlow services (2d)
        ┤ Phase 2.5: Replace global singletons    (0.5d)
        ┤                                        Total: 2.5 days

Week 4  ┤ Phase 2.2: Deploy SandboxPort in tools  (2d)
        ┤ Phase 2.4: Resolve __import__() hacks   (1d)
        ┤                                        Total: 3 days

Week 5  ┤ Phase 2.3: Eliminate StateCoordinator   (1d)
        ┤ Buffer / cross-cutting regression tests
        ┤                                        Total: ~2 days

Week 6  ┤ Phase 3.1: Delete dead files            (0.5d)
        ┤ Phase 3.2: Deprecate with shims         (0.5d)
        ┤ Phase 3.3: Promote to correct layers    (2d)
        ┤                                        Total: 3 days

Week 7  ┤ Phase 3.4: Freeze untouchable modules   (0.5d)
        ┤ Phase 3.5: Update .importlinter         (0.5d)
        ┤ Buffer / fix import breakages
        ┤                                        Total: ~2 days

Week 8  ┤ Phase 4.1: Architecture fitness tests   (1d)
        ┤ Phase 4.4: Importlinter in CI           (0.5d)
        ┤ Phase 4.7: Shared event reconstructor   (0.5d)
        ┤                                        Total: 2 days

Week 9  ┤ Phase 4.2: Prometheus metrics or remove (1d)
        ┤ Phase 4.5: Contract tests               (1d)
        ┤                                        Total: 2 days

Week 10 ┤ Phase 4.3: Web API auth middleware      (1d)
        ┤ Phase 4.6: Architecture ADRs            (1d)
        ┤ Final audit verification                (1d)
        ┤                                        Total: 3 days

─────────────────────────────────────────────────────────
TOTAL: 10 weeks · ~27 person-days (with buffers)
```

---

## 7. Architecture Quality Gates

Every phase concludes with these gates. All must pass before the phase is marked complete.

| Gate | Command | Phase applicability |
|------|---------|-------------------|
| **G1: Domain purity** | `grep -rn "from weebot.infrastructure\|from weebot.application\|from weebot.interfaces\|from weebot.core" weebot/domain/` → 0 results | All phases |
| **G2: importlinter** | `import-linter` → 0 contract violations | Phase 3+ |
| **G3: No `__import__()` hacks** | `grep -rn "__import__(" weebot/application/ --include="*.py"` → 0 results | Phase 2+ |
| **G4: All commands/queries registered** | `pytest tests/unit/test_architecture_fitness.py -k "handler"` → pass | Phase 1+ |
| **G5: Full test suite** | `pytest tests/ -x --tb=short` → all pass | All phases |
| **G6: No flat files at root** | `ls weebot/*.py \| wc -l` → ≤ 5 (only allowed shims) | Phase 3+ |
| **G7: Sandbox enforcement** | `grep -rn "subprocess.run\|os.system" weebot/tools/ --include="*.py"` → 0 results | Phase 2+ |

---

## 8. Risk Register

| ID | Risk | Probability | Impact | Mitigation |
|----|------|-------------|--------|------------|
| R1 | Moving flat files breaks import chains in undocumented consumers | High | Medium | Each move leaves a shim. Run full test suite after each move batch. |
| R2 | `EventBrokerAdapter.subscribe()` creates race conditions with legacy consumers | Medium | High | Contract tests (Phase 4.5) catch regressions. |
| R3 | `ComplexTaskExecutor` consumers have no migration path to `PlanActFlow` | High | Medium | Phase 3 freezes them; Phase 3.5 documents sunset timeline. |
| R4 | Removing `prometheus-client` breaks undocumented monitoring dashboards | Low | Low | Search for any `prometheus_client` imports before removal. |
| R5 | Architecture fitness tests are too brittle — flag false positives on intentional exceptions | Medium | Low | Tests allow exemption comments (e.g., `# noqa: ARCH-OK`) for reviewed exceptions. |

---

## 9. Success Metrics

| Metric | Baseline (June 2026) | Target (after Phase 4) |
|--------|---------------------|------------------------|
| Flat files at `weebot/` root | 35 | ≤ 5 (allowed shims only) |
| `__import__()` calls in application layer | 10 | 0 |
| Unregistered CQRS queries | 4 | 0 |
| Parallel state management systems | 4 | 1 (StateRepositoryPort) |
| Parallel orchestration engines | 2 | 1 primary + 1 frozen legacy |
| Event system bridging completeness | Publish only | Publish + Subscribe |
| `ScoringPort` DI default | noop lambda | Real adapter |
| `SandboxPort` tool coverage | 0 of 3 tools | 3 of 3 tools |
| Global singletons | 2 | 0 |
| API authentication | None | API key middleware |
| Architecture fitness tests | Present, unknown enforcement | 10 tests, passing in CI |
| importlinter CI enforcement | Configured, unverified | CI job, 0 violations |
| ADRs documented | 0 | 5 |
| `PlanActFlow` line count | ~300 | ≤ 200 |
| `core/` module classification | Undocumented | Documented in dedicated file |
| Stray files at project root | 6 HTML/CSS files | 0 (move to `docs/examples/`) |

---

## 10. Appendix: File Manifest

### 10.1 Files to Create

| File | Phase | Purpose |
|------|-------|---------|
| `docs/CORE_MODULE_CLASSIFICATION.md` | 1.5 | Classification of all 26 `core/` modules |
| `weebot/application/services/context_switcher.py` | 2.1 | Extracted model selection logic from PlanActFlow |
| `weebot/application/services/plan_history.py` | 2.1 | Extracted undo/redo stack from PlanActFlow |
| `weebot/application/services/continuation_detector.py` | 2.1 | Extracted prompt enrichment from PlanActFlow |
| `tests/integration/test_event_bridge_contract.py` | 4.5 | Contract tests for full event bridge |
| `weebot/application/cqrs/event_reconstructor.py` | 4.7 | Shared TypeAdapter-based event reconstruction |
| `docs/adr/001-pydantic-over-dataclasses.md` | 4.6 | Architecture Decision Record |
| `docs/adr/002-mediator-over-service-layer.md` | 4.6 | Architecture Decision Record |
| `docs/adr/003-protocol-vs-abc-ports.md` | 4.6 | Architecture Decision Record |
| `docs/adr/004-sqlite-over-postgres.md` | 4.6 | Architecture Decision Record |
| `docs/adr/005-in-process-event-bus.md` | 4.6 | Architecture Decision Record |
| `tests/unit/test_architecture_fitness.py` | 4.1 | 10 automated architecture fitness tests (if not already robust) |

### 10.2 Files to Delete

| File | Phase | Reason |
|------|-------|--------|
| `weebot/source_credibility_assessment.py` | 3.1 | Dead code |
| `weebot/learning_from_executions.py` | 3.1 | Dead code (superseded by SkillOpt) |
| `weebot/customized_suggestions.py` | 3.1 | Dead code |
| `weebot/interface_customization.py` | 3.1 | Dead code |
| `weebot/intelligent_template_suggestion.py` | 3.1 | Dead code |
| `weebot/automatic_template_adaptation.py` | 3.1 | Dead code |
| `weebot/notifications_categorizer.py` | 3.1 | Dead code |
| `pricing_example.html` | 4.x | Stray artifact |
| `pricing_external.html` | 4.x | Stray artifact |
| `pricing_external_clean.html` | 4.x | Stray artifact |
| `pricing_external_final.html` | 4.x | Stray artifact |
| `pricing_external_simple.html` | 4.x | Stray artifact |
| `pricing_section.html` | 4.x | Stray artifact |
| `pricing-styles.css` | 4.x | Stray artifact |
| `responsive_test.html` | 4.x | Stray artifact |

### 10.3 Files to Move

See Phase 3.3 Bucket C table for all 24 file relocations.

### 10.4 Files with Significant Modifications

| File | Phases | Nature of change |
|------|--------|-----------------|
| `weebot/application/di.py` | 1.2, 1.4, 2.2, 2.4, 3.3 | New scorer wiring, query handler registration, sandbox binding, StateCoordinator elimination |
| `weebot/application/cqrs/handlers.py` | 1.4, 2.4 | 4 new query handlers, `__import__()` removal |
| `weebot/application/flows/plan_act_flow.py` | 2.1 | Extract 3 services, reduce to ≤200 lines |
| `weebot/core/agent_context.py` | 1.1, 1.3 | Remove StateManager, bridge EventBroker subscriptions |
| `weebot/tools/bash_tool.py` | 2.2 | Route execution through SandboxPort |
| `weebot/tools/python_tool.py` | 2.2 | Route execution through SandboxPort |
| `weebot/tools/powershell_tool.py` | 2.2 | Route execution through SandboxPort |
| `weebot/infrastructure/event_bus.py` | 3.5 | Add DeprecationWarning to global singleton |
| `weebot/infrastructure/events/broker_adapter.py` | 1.3 | Add subscribe() bridge method |
| `weebot/interfaces/web/main.py` | 5.2, 5.3 | Add /metrics endpoint, auth middleware |
| `.importlinter` | 3.5, 4.4 | Update contracts, add flat-file elimination rule |

---

**Plan version:** 1.0  
**Last updated:** 2026-06-01  
**Next review:** After Phase 1 completion (Week 2)
