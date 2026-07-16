# Weebot Architecture Audit v2.0

**Date:** 2026-06-19  
**Epistemic Protocol:** EGFV — every non-trivial claim inline-labelled  
**Project:** weebot — AI Agent Framework  
**Audit scope:** Full codebase (~57K lines Python, excluding GitNexus submodule)

---

## Phase 1 — Architectural Fingerprinting

### DETECTED ARCHITECTURE: Clean Architecture / Hexagonal (Ports & Adapters) with Agent Pipeline

**Evidence:**

1. **Four-layer import discipline** [VERIFIED] — `cli/main.py:12-17` imports `weebot.application.di.Container` + `weebot.application.ports.state_repo_port.StateRepositoryPort`; never imports infrastructure directly. `weebot/interfaces/web/main.py:13-24` imports ports + routers; infrastructure imports are lazy inside `lifespan()`.

2. **Port/Adapter directory topology** [VERIFIED] — 55+ ABC/Protocol files in `weebot/application/ports/` with matching adapters in `weebot/infrastructure/adapters/` and `weebot/infrastructure/persistence/`. Composition root at `weebot/application/di/__init__.py` wires `Port → Adapter` bindings via `register(port_type, factory)` [VERIFIED — `weebot/application/di/__init__.py:160-210`].

3. **Domain layer purity** [VERIFIED] — `weebot/domain/models/` contains Pydantic `BaseModel` entities (Plan, Session, Step, Event, Skill) with no imports from application, infrastructure, or interfaces layers. Architecture test at `tests/unit/test_architecture_fitness.py:42` verifies `test_domain_has_no_outer_imports`.

4. **DI container at composition root** [VERIFIED] — `weebot/application/di/__init__.py:90-240` — `Container` dataclass with 6 mixin classes; `configure_defaults()` registers 30+ bindings; `get(port)` resolves singletons via lazy factory.

5. **Agent pipeline overlay** [VERIFIED] — Within the application layer, a finite state machine (`PlanActFlow.run()` at `plan_act_flow.py:392`) routes through: PlanningState → ExecutingState → UpdatingState → SummarizingState → CompletedState. Each state is a separate module in `weebot/application/flows/states/`.

### Dominant Patterns

| Pattern | Layer | Evidence |
|---|---|---|
| Clean Architecture | All | 4 distinct layers (domain, application, infrastructure, interfaces) [VERIFIED] |
| Agent FSM Pipeline | Application | 5-state loop in `plan_act_flow.py:392-620` [VERIFIED] |
| Service Locator DI | Application/DI | `Container.get()` singleton-per-type cache [VERIFIED — `di/__init__.py:135`] |
| Immutable domain entities | Domain | Pydantic `model_copy()` pattern on Session/Plan mutations [VERIFIED — `session.py:89-96`] |
| Async generators as event buses | Application | `PlanActFlow.run()` is an `AsyncGenerator[AgentEvent]` [VERIFIED — `plan_act_flow.py:392`] |
| Model cascade routing | Application/Agents | `ExecutorAgent._call_with_cascade()` at `executor/_base.py:515` [VERIFIED] |
| Singleton global state | Core + Infrastructure | `~30+ files` use module-level `global` or singleton patterns [VERIFIED] |

### Architectural Drift Detected

The project **intends** Clean Architecture but has **accumulated significant drift** in two dimensions:

1. **Singleton proliferation in Core layer** — `core/` contains 10+ module-level singletons (`_global_handler`, `_global_monitor`, `_tracker_registry`, `_guard`, etc.) that bypass the DI container and create implicit coupling between consumers. [VERIFIED — 30+ files with `global` keyword]

2. **Services ↔ Flows circular package dependency** — `weebot/application/services/task_runner.py:7` imports `from weebot.application.flows.base_flow import BaseFlow` while `weebot/application/flows/plan_act_flow.py:24-44` imports from multiple services. [VERIFIED]

---

## Phase 2 — Compliance Matrix

| Module | Detected Pattern | Intended Pattern | Drift | Violations | Severity | Evidence |
|---|---|---|---|---|---|---|
| `cli/main.py` | Thin entry point | Interfaces layer | None | 0 | — | `cli/main.py:12-17`, no infra imports |
| `weebot/interfaces/web/main.py` | Thin entry point | Interfaces layer | Minor | Lazy infra imports in lifespan | LOW | `web/main.py:60` (lifespan imports infra) |
| `weebot/interfaces/gateways/` | Adapter pattern | Interfaces layer | Minor | 3/6 gateways not exported from `__init__.py` | LOW | `gateways/__init__.py` lists 2 of 6 adapters |
| `weebot/application/agents/` | Agent pipeline | Application layer | Medium | 2 lazy infra imports in `executor/_base.py` | MEDIUM | `executor/_base.py:350,360` |
| `weebot/application/flows/` | FSM pipeline | Application layer | Medium | 4 lazy infra imports + circular dep with services | MEDIUM | `flows/plan_act_flow.py:24-44` vs `services/task_runner.py:7` |
| `weebot/application/services/` | Domain services | Application layer | High | 7 lazy infra imports | HIGH | 7 files import infrastructure directly |
| `weebot/application/di/` | Composition root | DI container | Minor | Manual service-locator vs auto-wiring | LOW | `di/__init__.py:90-240` |
| `weebot/domain/models/` | Pure entities | Domain layer | None | 0 | — | 55 Pydantic models, no outer imports |
| `weebot/core/` | Cross-cutting | Shared kernel | High | 10+ module-level singletons bypass DI | HIGH | `core/safety.py:19`, `core/alerting.py:319`, etc. |
| `weebot/infrastructure/` | Adapters | Infrastructure | None (by design) | 0 | — | All infra adapters implement port interfaces |
| `weebot/tools/` | Tool execution | Infrastructure | Medium | 3 tools use global singletons + direct infra imports | MEDIUM | `tools/schedule_tool.py:18`, `tools/advanced_browser.py:28` |

---

## Phase 3 — Dependency and Coupling Analysis

### 3.1 Circular Dependencies

**Package-level cycle: services ↔ flows** [VERIFIED]

```
weebot/application/services/task_runner.py:7
  → from weebot.application.flows.base_flow import BaseFlow
  
weebot/application/flows/plan_act_flow.py:24-44
  → from weebot.application.services import (memory_compactor, context_switcher, ...)
  
weebot/application/flows/states/completed.py:46
  → from weebot.application.services import (IdeaGate, IntentReviewService, MainReviewService)
```

**Impact:** TaskRunner creates `PlanActFlow` instances (line 247). PlanActFlow depends on services from the same package it's re-exported from. This tangles creation and orchestration. [VERIFIED]

### 3.2 Layer Leaks

**Application → Infrastructure (13 lazy imports)** [VERIFIED]

All are lazy (inside-function), but 7 are in `application/services/` — the worst layer for this. Key offenders:
- `model_selection.py:3256` imports `adapter_factory.create_adapter` directly
- `task_runner.py:22` imports `infrastructure.observability.metrics`
- `meta_self_improver.py:24,69` imports `MetaImprovementLog`

**Core layer is the most entangled** [VERIFIED] — Core modules import from each other in a mesh pattern. `core/bash_guard.py` depends on `core/approval_policy.py` which depends on regex patterns defined at module scope. No DI mediation.

### 3.3 Shared Mutable State

**30+ global singleton files** [VERIFIED]. Concentrated in:

| Layer | Count | Examples |
|---|---|---|
| `core/` | 10 | `_global_handler`, `_global_monitor`, `_tracker_registry`, `_guard`, `_analyzer` |
| `infrastructure/` | 11 | `event_bus._metrics`, `connection_pools`, `security_verifiers` |
| `tools/` | 5 | `schedule_tool._scheduler`, `advanced_browser._playwright_instance` |
| `qmd_integration/` | 4 | `_embeddings`, `_client`, `_rag_engine`, `_expander` |

**Risk:** Concurrent access to singletons without locking. `SchedulingManager._running_jobs: set` (`scheduler.py:105`) uses a Python `set` for dedup — this is not thread-safe for asyncio. [VERIFIED]

### 3.4 Tight Coupling Hotspots

**Hotspot #1: ExecutorAgent._call_with_cascade()** [VERIFIED — `executor/_base.py:515-650`]: 650-line method that:
- Manages parallel model dispatch with `asyncio.wait(FIRST_COMPLETED)`
- Maintains its own circuit breaker dictionary per model (`_circuit_breaker_failures`)
- Falls back through 4 tiers
- Makes live API calls to OpenRouter for model discovery
- Handles error classification and retry
This is a **god method** inside a 1,400-line god module.

**Hotspot #2: model_selection.py** [VERIFIED — 3,265 lines]: The single largest file, responsible for model registry configuration. 2.3× larger than any other module. The entire model cascade configuration (`ROLE_MODEL_CONFIG`) lives here — removing a model requires editing this file.

**Hotspot #3: PlanActFlow._emit()** [VERIFIED — `plan_act_flow.py:244-315`]: Serialization bottleneck. Every event passes through this single method for: truth binding, credential sanitization, session mutation, event bus publishing, and DB persistence. A single failure here blocks all output.

---

## Phase 4 — AI Orchestrator Deep Review

### ORCHESTRATION MODEL

**Centralized FSM** [VERIFIED — `plan_act_flow.py:392-620`]: All execution paths route through `PlanActFlow.run()`, which iterates through a finite state machine with 5 states. `ExecutorAgent.execute_step()` is called from `ExecutingState`. This is a single-coordinator model.

**Routing separation:** Partial [HYPOTHESIS]. The planner (`PlannerAgent`) and executor (`ExecutorAgent`) are separate classes, but both are instantiated inside `PlanActFlow.__init__()` [VERIFIED — `plan_act_flow.py:205-238`]. There is no independent routing layer — routing is hardcoded in the FSM loop.

**Provider abstraction:** Good [VERIFIED]. `LLMPort` defines a single `chat()` interface. `AdapterFactory` wraps every provider in `ResilientLLMAdapter`. `DirectOrFallbackAdapter` supports direct-to-OpenRouter fallback. 6 concrete providers implement `LLMPort`.

### ASYNC AND CONCURRENCY

**Pattern consistency:** Good [VERIFIED]. `PlanActFlow.run()` is an `AsyncGenerator`. All agent methods are `async def`. State transitions are non-blocking. 

**Backpressure:** Partial [HYPOTHESIS]. `DispatchAgentsTool` and `MixtureOfAgentsTool` use `asyncio.Semaphore(4)` [VERIFIED]. But the cascade dispatcher fires 3 models concurrently with no semaphore — if cascading across 8 roles, that's 24+ concurrent LLM calls. No global limit exists.

**Concurrent LLM bounding:** `asyncio.wait(FIRST_COMPLETED, timeout=90s)` for parallel calls; 60s for sequential fallbacks [VERIFIED — `_base.py:597-612`]. Cancellation cleans up pending futures. No deadlock risk but potential for unbounded concurrency under load.

### STATE AND CONTEXT

**Session state propagation:** Semi-implicit [VERIFIED]. Session uses `model_copy()` — a functional update pattern — but the reference is stored in `PlanActFlow._session` and shared with states via the flow context. Not purely functional, not purely mutable.

**Memory boundaries:** Defined [VERIFIED]. `SessionContext` has explicit fields (`facts`, `original_task`, `meta_notes`, `archived`) + `extra` dict for overflow. `MemoryCompactor` provides summarization but was previously a dead code path (fixed in recent commit).

**Context propagation:** The FSM loop re-reads `self._session.status` and `self._plan` at each iteration boundary. This is a clean implicit contract — no explicit return values, but observable state transitions.

### FAILURE SEMANTICS

**Retry:** 3-layer system: circuit breaker (3 failures → 60s cooldown), retry backoff (7-step exponential), cascade fallback (4-tier model chain). [VERIFIED — `circuit_breaker.py:63-90`, `backoff.py:18-27`, `_base.py:515-650`]

**Fallback:** `DirectOrFallbackAdapter` (direct API → OpenRouter) + model cascade (Moonshot → NVIDIA → DeepSeek → OpenAI OSS → NousResearch → xAI). Live model rescue as last resort. [VERIFIED]

**Partial failure:** Comprehensive taxonomy [VERIFIED — `_base.py:712-1195`]: 4× repeated tool calls → abort; 2× repeated assistant turns → abort; same error class N× → HITL; trajectory diagnosis → recovery injection (×2) or abort; all tools failed → abort; budget exhausted → abort. Failed steps yield `StepEvent(FAILED)` and trigger replanning via `Plan.merge()`.

**Edge case:** `AllModelsTrippedError` is terminal — flow cannot recover if all model tiers are exhausted. [VERIFIED — `_base.py:917-928`]

### TOOL EXECUTION

**Isolation:** Partial [HYPOTHESIS]. Tools are `BaseTool` subclasses registered in `RoleBasedToolRegistry`. Tool execution happens in `ToolCollection.execute()` which iterates through tools with semaphore gating. However, 30% of tools use global singletons (`schedule_tool._scheduler`, `advanced_browser._playwright_instance`) — these are not isolated.

**Validation:** Tools return `ToolResult(success=True/False, output, error)`. Error classification happens post-execution in `_classify_tool_error()` [VERIFIED — `_base.py:124-143`]: maps to `confirmation_required`, `policy_denied`, `security_blocked`, `timeout`, `permission_denied`.

**Security:** Multi-layer bash safety: `CommandSecurityAnalyzer` → `BashGuard` → `ExecApprovalPolicy` [VERIFIED — `bash_tool.py:105-141`]. Financial tools have `FORCE_ALWAYS_ASK` mode [VERIFIED — `approval_policy.py:44`].

### SCALABILITY BOTTLENECKS

**Single point most likely to fail under 10x load [HYPOTHESIS]:** `PlanActFlow._emit()` at `plan_act_flow.py:244-315` — it's the event serialization bottleneck. Every event from every state passes through this method for: truth binding, credential sanitization, session mutation, event bus publish, domain event publish, and DB persistence. A DB lock here stalls the entire flow. Under concurrent flows (10× sessions), the SQLite WAL lock serializes all writes.

**Statelessness:** The orchestrator is stateful. `PlanActFlow` holds `self._session`, `self._plan`, `self._state`. Sessions are persisted to SQLite but the runtime state lives in memory — there's no horizontal scaling without sticky sessions.

### Stack-Specific Checks

- **FastAPI** (`weebot/interfaces/web/main.py`): Uses `lifespan` for startup/shutdown. No explicit background task usage detected for agent runs [HYPOTHESIS — `main.py:60`]. WebSocket pathways are separate from REST — good isolation.
- **Redis**: Listed in `requirements.txt` but no production usage found in the codebase [VERIFIED — Redis import only in `requirements.txt`, not in source].
- **Docker**: `docker-compose.yml` has `api` and `web` services — service boundaries reflect REST API + frontend, but the agent orchestration runs inside the `api` container with no process isolation from HTTP serving. [VERIFIED — `Dockerfile.api:23` runs uvicorn directly on the agent app].

---

## Phase 5 — Anti-Pattern Detection

### Detected

**1. God Module — `model_selection.py` (3,265 lines)** [VERIFIED]  
Severity: HIGH. Contains the entire model registry, cascade configuration, role mapping, and cost tiers in a single file. Any model change requires editing this 3,200-line file. Should be decomposed into per-provider registry modules.

**2. God Method — `ExecutorAgent._call_with_cascade()` (~650 lines)** [VERIFIED — `executor/_base.py:515-650`]  
Severity: HIGH. Manages parallel dispatch, circuit breaker, fallback chain, model discovery, error classification, and result aggregation in a single method. Should be refactored into separate cascade-strategy classes.

**3. Services ↔ Flows Circular Dependency** [VERIFIED]  
Severity: HIGH. `services/task_runner.py` imports `flows/base_flow.py`; `flows/plan_act_flow.py` imports from `services/`. Creates a package-level dependency cycle that makes them impossible to test independently.

**4. Singleton Proliferation (30+ globals)** [VERIFIED]  
Severity: MEDIUM. Module-level singletons in `core/`, `tools/`, and `infrastructure/` bypass the DI container. Creates implicit coupling — consumers cannot inject alternate implementations for testing.

**5. Premature Abstraction (25 single-implementation ports)** [VERIFIED]  
Severity: MEDIUM. 47% of the 55+ port interfaces have exactly one concrete implementation. The interface adds indirection without polymorphism. Examples: `CheckpointPort` → `SQLiteCheckpointStore`, `SoulProviderPort` → `FileSystemSoulProvider`. Also 2 ports with zero implementations (`CapabilityGatePort`, `TruthBindingPort`) — dead abstraction.

**6. Orchestrator Bottleneck — PlanActFlow._emit()** [VERIFIED — `plan_act_flow.py:244-315`]  
Severity: MEDIUM. Single serialization point for truth binding, credential sanitization, session mutation, event bus publishing, and DB persistence. A slow DB operation here blocks event output for the entire flow.

**7. Shared Database Coupling** [VERIFIED]  
Severity: LOW. Multiple services share SQLite tables (sessions, events, jobs) via `StateRepositoryPort`. Not cross-service coupling (single-process), but does create schema coupling across service boundaries.

**8. Anemic Domain Model — Partial** [HYPOTHESIS]  
Severity: LOW. `Session`, `Plan`, and `Step` models have meaningful methods (`add_event`, `update_step_status`, `merge`, `is_complete`), but 80%+ of domain models are pure data containers with zero business logic. The service layer compensates, but this is expected in Pydantic-based domains.

### NOT Detected

- **Hidden Monolith**: NOT detected. Service boundaries exist; each state/agent/service has clear responsibility even if coupling is imperfect.
- **Overengineering**: NOT detected. The abstractions are proportional to the system's complexity (agent pipeline, model cascade, tool registry).
- **Underengineering**: NOT detected. Critical boundaries (domain, ports, DI) exist and are enforced by architecture tests.

---

## Phase 6 — Executive Summary

### ARCHITECTURE SCORE: 6 / 10

**Justification:** The Clean Architecture foundation is solid — 4 layers with enforced import rules, 55+ port interfaces, and architecture tests that catch regression. However, moderate drift has accumulated: 30+ global singletons bypass the DI container, a circular dependency between services and flows, a god module at 3,265 lines, and lazy infrastructure imports in the application layer. The architecture is recognizable but needs structural cleanup in the services/flows boundary and singleton management to reach 8/10.

### MATURITY LEVEL: Early Production

**Justification:** Architecture tests exist and gate CI. DI container is functional. Agent pipeline has comprehensive failure handling. But the services/flows cycle, god modules, and singleton proliferation indicate architectural debt from feature velocity. Fit for current load but will degrade under team scaling.

### PRIMARY RISKS (ranked by impact)

1. **services ↔ flows circular dependency** — makes independent testing impossible; any refactor of one requires touching both. Risk of cascading regressions on every change. [VERIFIED — `task_runner.py:7` ↔ `plan_act_flow.py:24-44`]

2. **PlanActFlow._emit() serialization bottleneck** — truth binding, credential sanitization, event bus publish, DB persistence all in one method. DB lock contention under concurrency stalls all event output. [VERIFIED — `plan_act_flow.py:244-315`]

3. **model_selection.py god module (3,265 lines)** — the model registry is a single point of configuration failure. Any model change requires editing a 3,200-line file with high merge-conflict risk. [VERIFIED]

4. **Singleton proliferation bypassing DI (30+ globals)** — testing and extension are impossible without monkey-patching. Singleton state leaks between test runs. [VERIFIED]

5. **ExecutorAgent._call_with_cascade() god method (650 lines)** — parallel dispatch, circuit breaker, fallback chain, error classification in one method. Changes to one cascade strategy risk breaking others. [VERIFIED — `executor/_base.py:515-650`]

### CRITICAL VIOLATIONS

None at the CRITICAL severity level. All violations are HIGH or MEDIUM. No security boundary violations, no systemic failure risk.

### REFACTOR URGENCY: Next Sprint

**Justification:** The services/flows cycle and god modules are actively costly — every feature touches `plan_act_flow.py` or `model_selection.py`. The singleton proliferation is less urgent because singletons are mostly idempotent (no mutable cross-consumer state). Address the cycle and god modules before adding new features that compound the problem.

---

## Phase 7 — Refactoring Roadmap

### IMMEDIATE (fix before next feature)

| Finding | Action | Expected Outcome |
|---|---|---|
| Services ↔ Flows cycle [Phase 3.1] | Move `BaseFlow` from `flows/` to `application/` root or create `application/abstractions/`. Services should depend on abstractions, not flow implementations. | Cycle broken; services and flows independently testable |
| `plan_act_flow.py._emit()` bottleneck [Phase 3.4, Hotspot #3] | Extract truth binding and credential sanitization into a middleware chain. Move DB persistence to a background task. | Reduced serialization latency; non-blocking event output |
| `model_selection.py` god module [Phase 5, #1] | Split into: `model_registry/models.py`, `model_registry/cascade_config.py`, `model_registry/cost_tiers.py`, `model_registry/provider_configs.py` | 3,265 lines → 4 files of ~800 lines each |

### HIGH-IMPACT (next sprint)

| Finding | Action | Expected Outcome |
|---|---|---|
| `_call_with_cascade()` god method [Phase 5, #2] | Extract strategy pattern: `CascadeStrategy(parallel_probes, fallback_chain, rescue_enabled)`. Each strategy is testable independently. | 650 lines → ~150 line orchestrator + 4 strategy classes |
| 25 single-implementation ports [Phase 5, #5] | Audit: keep ports that are DI boundaries (LLM, State, Sandbox). Demote ports with 0-1 implementations to direct service classes. | Reduced indirection; clearer dependency graph |
| 30+ global singletons [Phase 5, #4] | Migrate the 10 most-used singletons to DI container registration. Leave tools' singletons (they're process-level resources). | 10 fewer monkey-patching targets; cleaner test setup |
| 13 lazy infra imports in application [Phase 3.2] | Convert to TYPE_CHECKING imports + protocol-based access. Inject infrastructure references through DI at runtime. | Application layer becomes infrastructure-free at import time |

### LONG-TERM (architectural evolution)

**Target-state architecture:** Keep Clean Architecture + Agent Pipeline, but evolve:
- Extract `application/abstractions/` for cross-package interfaces (breaks services/flows cycle)
- Add `application/strategies/` for cascade and retry strategies
- Add `application/middleware/` for event processing pipeline (truth binding, sanitization, audit logging)
- Promote `core/` singletons to DI-managed services where they cross package boundaries

**Migration sequence:**
1. Break services/flows cycle first (unblocks all other refactoring)
2. Extract cascade strategies (highest risk code, highest test value)
3. Split model_selection.py (highest merge-conflict surface)
4. Migrate core singletons to DI (one per sprint, lowest risk)
5. Audit and collapse single-implementation ports

**Risk per migration:**
- Breaking services/flows cycle: MEDIUM — many imports to update, but architecture tests catch regressions
- Extracting cascade strategies: HIGH — cascade is the hot path; needs full integration test coverage first
- Splitting model_selection.py: LOW — pure data reorganization, no behavior change
- Migrating singletons: LOW per singleton — DI injection is additive

### SWITCHING TRIGGERS (conditions that would force architectural change)

1. **Multi-process deployment** — If the agent moves from single-process to multi-process (separate workers for planning vs execution), the implicit session state propagation in `PlanActFlow._session` must become explicit message passing with serializable state.
2. **Multi-tenant isolation** — If the platform serves multiple organizations, the 30+ global singletons become per-tenant and must move to DI with scoped lifetimes.
3. **Model registry as external service** — If model availability moves to an external configuration service, `model_selection.py` becomes a thin client and the 3,265-line registry file is deprecated.
4. **Tool marketplace** — If tools become pluggable from external sources (beyond MCP), the `RoleBasedToolRegistry` must support dynamic registration without restart.
