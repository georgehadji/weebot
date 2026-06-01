# Architecture Audit Report — weebot AI Orchestrator

**Auditor Role:** Principal Engineer / Architecture Governance Auditor  
**Audit Date:** 2026-06-01  
**Branch:** `feat/sia-integration`  
**Methodology:** Deep static analysis, AST-based boundary checking, cross-module dependency tracing, pattern compliance review  

---

## 1. Executive Summary

### Overall Architecture Score: **6.4 / 10**

| Dimension | Score | Rationale |
|---|---|---|
| Correctness of implementation | 5/10 | Significant boundary violations persist in production paths |
| Enforcement consistency | 5/10 | Fitness tests exist but carry 20+ acknowledged-exception carve-outs |
| Scalability | 7/10 | Async-first, connection pooling, model cascade; limited by single SQLite file |
| Maintainability | 6/10 | Clean arch intent is clear; dual-stack legacy/clean creates confusion |
| Observability | 7/10 | Prometheus metrics, health checks, structured events — well executed |
| Extensibility | 8/10 | Port/adapter model and CQRS pipeline allow clean extension |
| Resilience under growth | 6/10 | Circuit breaker + retry solid; single-DB SPOF, no message queue |

### Architectural Maturity Level: **Level 3 — Aspirational Architecture**

> Architecture framework is designed and partially implemented. Migration from legacy patterns is in progress with an explicit remediation plan. Architectural rules are enforced by fitness tests but carry a large carve-out allowlist, indicating that implementation lags design intent.

### Primary Risks

1. **Domain purity violation** propagated through `user_profile.py` into the clean architecture core
2. **~20 root-level legacy flat files** creating transitive pollution of application-layer services
3. **CQRS command handlers do NOT persist session state**, creating a silent divergence from the flow-based path
4. **Duplicate `ValidationBehavior`** definitions with subtly different async handling semantics
5. **Shared mediator singleton** mutated by `SkillOptFlow` construction — parallel training runs accumulate duplicate pipeline behaviors

### Refactor Urgency: **HIGH for domain boundary; MEDIUM for structural cleanup**

---

## 2. Intended vs Actual Architecture

### Intended Architecture

The declared target (evidenced by `ARCHITECTURE_REMEDIATION_PLAN.md`, `docs/adr/`, and `test_architecture_fitness.py`) is:

```
Interfaces → Infrastructure → Application → Domain
          ↑ (only DI container crosses all layers)
```

With three supporting patterns:
- **Hexagonal (Ports & Adapters)** — every external resource behind an ABC port
- **CQRS + Mediator** — all state mutations via commands, reads via queries, cross-cutting via pipeline behaviours
- **Event-Sourced Sessions** — session state rebuilt from immutable event log

### Actual Architecture

```
Domain  ←── weebot.nlp_understanding      (ROOT SHIM)   ← VIOLATION
        ←── weebot.multi_source_research  (ROOT SHIM)   ← VIOLATION
        ←── weebot.information_synthesis  (ROOT SHIM)   ← VIOLATION

Application/Services ←── weebot.tools.web_search              ← VIOLATION
                     ←── weebot.tools.advanced_browser         ← VIOLATION
                     ←── weebot.external_service_integration   ← VIOLATION

Application/Flows ←── weebot.nlp_understanding                 ← VIOLATION

PlanActFlow._emit()          ─────────────────→ StateRepo.save_session()  ✓
CQRS CreatePlanHandler       ─────────────────→ NO save_session()         ← DIVERGENCE
```

### Drift Summary

| Area | Intended | Actual | Verdict |
|---|---|---|---|
| Domain purity | Zero outer imports | 3 root-module imports in `user_profile.py` | DRIFT |
| CQRS as primary dispatch | All mutations via Mediator | `PlanActFlow` still dispatches agents directly when `_mediator is None` | PARTIAL |
| All ext resources behind ports | Every tool via SandboxPort/BrowserPort | 3 tool classes, 3 service classes bypass ports | DRIFT |
| Single composition root | Only `di.py` constructs adapters | `di.py` + `agent_factory.py` + several tools construct infra objects | PARTIAL |
| Legacy files eliminated | Phase 3 complete | 20+ legacy shims still at `weebot/` root | INCOMPLETE |
| No direct DB in tools | Tools use ToolRepositoryPort | 3 tools (knowledge, product, video_ingest) use sqlite3 directly | DRIFT |
| Settings via DI injection | ToolConfig for all tools | 4 tools import `WeebotSettings` directly | DRIFT |

---

## 3. Architecture Compliance Matrix

| Module | Intended Pattern | Actual Implementation | Violations | Severity |
|---|---|---|---|---|
| `domain/models/user_profile.py` | Pure Pydantic, zero outer deps | Imports `nlp_understanding`, `multi_source_research`, `information_synthesis` at module level | Domain boundary violation | **CRITICAL** |
| `domain/models/plan.py` | Immutable value object | Correctly implemented (model_copy pattern) | None | ✅ |
| `domain/models/session.py` | Immutable event log carrier | Correctly implemented | None | ✅ |
| `domain/models/event.py` | Typed discriminated union | Correctly implemented | None | ✅ |
| `application/agents/executor.py` | Application pure, no infra | Imports `weebot.tools.base` and `weebot.core.error_classifier` at module level | Layer boundary violation | MEDIUM |
| `application/cqrs/mediator.py` | Single Mediator dispatcher | Contains `LoggingBehavior`, `ValidationBehavior`, AND `ValidationGateBehavior` | God class; behavior duplication | MEDIUM |
| `application/cqrs/behaviors/validation.py` | Single source of truth | Duplicates `ValidationBehavior` from mediator.py (with different async handling) | Duplicate definition | MEDIUM |
| `application/services/multi_source_research.py` | Application service, port-only deps | Directly imports `WebSearchTool`, `AdvancedBrowserTool`, `external_service_integration` | Infrastructure leakage into application | HIGH |
| `application/services/complex_task_executor.py` | Application service | Imports `weebot.strategy_adaptation` (root shim), `weebot.core.workflow_orchestrator` | Legacy coupling | MEDIUM |
| `application/flows/workflow_planner.py` | Flow with clean deps | Imports `weebot.nlp_understanding` (root shim) | Infrastructure leakage | MEDIUM |
| `application/cqrs/handlers.py` | State-mutating, persists via repo | `CreatePlanHandler` and `UpdatePlanHandler` do NOT call `state_repo.save_session()` | Silent state divergence from PlanActFlow | HIGH |
| `tools/bash_tool.py` | Config via DI (ToolConfig) | Imports `WeebotSettings` directly | Settings coupling | MEDIUM |
| `tools/knowledge_tool.py` | Persistence via port | Direct `sqlite3` import | DB bypass | MEDIUM |
| `infrastructure/adapters/llm/` | Implements LLMPort | Correctly isolated behind port + factory | None | ✅ |
| `infrastructure/persistence/sqlite_state_repo.py` | Implements StateRepositoryPort | Correctly isolated | None | ✅ |
| `infrastructure/event_bus.py` | Implements EventBusPort | Correctly isolated | None | ✅ |
| `infrastructure/sandbox/` | Platform-dispatched SandboxPort impl | Correctly factory-dispatched | None | ✅ |
| `interfaces/web/main.py` | Entry point only | Exception handler, CORS, API key auth — well isolated | None | ✅ |
| `weebot/models/structured_output.py` | Should be domain/models | No weebot imports but lives outside domain/ | Confusing placement | LOW |

---

## 4. Dependency Analysis

### 4.1 Circular Dependencies

**CONFIRMED RISK — not currently circular but structurally primed:**

The application service modules form a transitive dependency ring via root-level shims:

```
application/services/information_synthesis.py
    ↓ imports
weebot.multi_source_research   (root shim)
    ↓ resolves to
application/services/multi_source_research.py   (post-migration destination)
```

When migration moves these to their final locations, a direct circular import will crystallize unless an intermediate port breaks the direction. This path is currently invisible because the root-shim layer absorbs the coupling.

The circular import test (`test_no_circular_imports`) is **`@pytest.mark.skip`** in CI — this risk is currently undetected at test time.

### 4.2 Boundary Violations (Confirmed by Static Analysis)

```
DOMAIN → ROOT SHIMS   (escapes importlinter domain-purity contract)

  weebot/domain/models/user_profile.py:21  →  weebot.nlp_understanding
  weebot/domain/models/user_profile.py:22  →  weebot.multi_source_research
  weebot/domain/models/user_profile.py:23  →  weebot.information_synthesis
```

**Why importlinter doesn't catch this**: The `.importlinter` `domain-purity` contract forbids `weebot.infrastructure`, `weebot.application`, `weebot.interfaces`, `weebot.core`, `weebot.tools`. It does **not** include root-level `weebot.*` shims (`weebot.nlp_understanding`, etc.) because importlinter treats them as valid internal imports. **The contract has a gap in its definition.**

### 4.3 Layer Leaks — Application → Infrastructure Bypasses

| Violating File | Bypassed Port | Direct Import |
|---|---|---|
| `application/services/multi_source_research.py` | `BrowserPort`, (no WebSearchPort exists) | `weebot.tools.web_search`, `weebot.tools.advanced_browser` |
| `application/agents/executor.py` | (no ToolPort exists) | `weebot.tools.base.ToolCollection` |
| `application/cqrs/handlers.py` | (no ToolPort exists) | `weebot.tools.base.ToolCollection` |

**Root cause**: There is no `ToolPort` or `ToolCollectionPort` in `application/ports/`. `ToolCollection` is treated as a first-class application concept, but it lives in the `tools/` infrastructure layer. This gap is by design for the ReAct pattern but means the hexagonal boundary between Application and Tools is unenforced.

### 4.4 Shared-State Risks

**Risk 1 — Shared SQLite file**: Sessions, skills, trajectories, tool definitions, summaries, and response cache all write to `weebot_sessions.db`. WAL mode allows concurrent readers but serializes all writers globally. Under `SkillOptFlow` batch_size=40 with multiple concurrent sessions, write throughput becomes a bottleneck with no per-domain isolation.

**Risk 2 — Mediator singleton mutation**: `build_skill_opt_flow()` calls `mediator.add_pipeline_behavior(gate)` on the shared singleton (di.py:457). Constructing multiple `SkillOptFlow` instances accumulates duplicate gates. The second epoch's `ApplySkillEditsCommand` will be validated twice — silent over-validation with no detection.

**Risk 3 — Concurrent `_session` mutation in `PlanActFlow._emit()`**: Each `await _emit(event)` does `self._session = self._session.add_event(event)` followed by `state_repo.save_session()`. If two coroutines emit simultaneously (e.g., event bus handler callback + flow loop), one write may overwrite the other's intermediate session state. There is no asyncio lock guarding this reassignment.

### 4.5 Tight Coupling Hotspots

1. **`di.Container`** — resolves 30+ singletons; factory method signature changes break all callers at runtime, not at import time.
2. **`ValidationGateBehavior.handle()`** — `cmd_name != "ApplySkillEditsCommand"` (string comparison); command rename breaks gate silently.
3. **`plan_act_flow.py:set_state()`** — `state_map` hardcodes all concrete state classes; adding a new state requires modifying this map.
4. **`EXECUTOR_SYSTEM_PROMPT`** — embedded module-level string constant; no versioning, no runtime override without subclassing.

---

## 5. AI Orchestrator Specific Review

### 5.1 Agent Orchestration Model

**Pattern**: ReAct (Reason + Act) loop inside `ExecutorAgent.execute_step()`.

**Strengths**: Bounded conversation buffer (`maxlen=max_context_turns`), hard `StepBudget` ceiling, model cascade for cost optimization, `ConversationCompressor` at 75% context usage.

**Weaknesses**:
- **No policy-error-loop detection**: agent exhausts 25 steps cycling through equivalent-but-distinct tool calls that all fail with the same error class. Identical-*signature* guard fires at 4; identical-*error-class* guard does not exist.
- **Fresh executor per step**: conversation history is step-scoped. Cross-step context is limited to the `context_lines` injected at step start — no persistent working memory carries tool call results forward.
- **`repeated_tool_calls >= 4` threshold** is too permissive: LLMs typically exhaust ~3 phrasings before looping identically, meaning the guard fires 12+ tool calls in.

### 5.2 Workflow Coordination

**Strengths**: Explicit state machine, testable state transitions, CQRS decoupling of planner from flow orchestration.

**Weaknesses**:
- `max_iterations = 50` hardcoded inside `run()` (line 170); not configurable via constructor.
- No back-pressure at `TaskRunner.submit()` beyond a queue-full error; the API layer has no rejection feedback mechanism.
- Silent degradation: when `_mediator is None`, `PlanningState` falls back to direct `PlannerAgent` calls with a `DeprecationWarning` instead of a hard failure. Misconfiguration is silently masked.

### 5.3 Message / Event Architecture

**Strengths**: Prometheus counter per event, per-handler fault isolation in `asyncio.gather`.

**Weaknesses**:
- **No durable event delivery**: in-memory only. Process crash between `_emit()` and `save_session()` loses the event with no journal.
- **`EventStorePort` not wired by default**: the append-only audit log adapter exists but is not registered in `configure_defaults()`. Audit log is opt-in.
- **No event replay**: sessions reconstruct from `events_json` but there is no `replay()` capability for partial state reconstruction.

### 5.4 Tool Execution Isolation

**Strengths**: 4-layer security analysis, platform-specific sandbox factory, `WORKSPACE_ROOT` path restriction.

**Weaknesses**:
- **`timeout` coercion bug**: `BashTool` does not coerce string timeout args to `float`; behavior is undefined (documented in execution-reliability-fix-plan.md Fix 4).
- **64KB output cap**: `sandbox_max_output_bytes=65536`. Large outputs silently truncated with no truncation marker to the agent.
- **`PowerShellTool` LangChain inheritance**: `PowerShellTool(langchain.tools.BaseTool)` runs synchronously; the `PowerShellBaseTool` wrapper hides this but does not add async timeout. The subprocess blocks the event loop via the sync `_run()` wrapper.

### 5.5 Context Propagation

**Weaknesses**:
- `Session.context` is untyped `Dict[str, Any]`; keys like `skill_name`, `skill_content`, `_original_task` are magic strings with no schema or contract.
- `session.context["facts"]` grows unboundedly with no eviction policy. Long-running sessions accumulate facts indefinitely.

### 5.6 Memory / State Boundaries

Four overlapping memory systems with no formal interface between them:
- `Session._memory_index` — in-process, cleared on deserialization
- `WorkingMemory` / `EpisodicMemory` — session-scoped, SQLite-backed
- `ConversationCompressor` — summarises in-context buffer at 75%
- `PersistentMemoryTool` — writes a flat `.md` file directly to disk (bypasses all ports)

`PersistentMemoryTool` bypasses all ports and writes to a hardcoded filesystem path. Persistent agent memory is not reproducible across deployments or machines.

### 5.7 Retry / Failure Semantics

| Layer | Retry Mechanism | Failure Behavior |
|---|---|---|
| LLM adapter | `RetryWithBackoff` (exp backoff + jitter) | Circuit breaker trips; cascade to next tier |
| Executor step | Model cascade FREE→BUDGET→PRIMARY | `StepBudget` exhaustion → `ErrorEvent` → UPDATING state |
| Flow iteration | `max_step_repetitions=3` per step | Force-complete step, transition to SUMMARIZING |
| Task runner | None | Failed session saved as FAILED; no requeue |
| CQRS handlers | `CommandResult.fail()` wraps all exceptions | Failure signal returned; no retry triggered |

**Gap**: No end-to-end retry at the session level. All three LLM tiers down → session fails permanently with no requeue.

### 5.8 Concurrency Model

Correctly async-first. `TaskRunner` uses `asyncio.PriorityQueue`. SQLite WAL handles read concurrency.

**Hard limit**: Not safe for multi-process deployment. SQLite has one write connection. Running two web server processes will cause write contention with no distributed lock. Horizontal scaling is limited to a single process.

### 5.9 Multi-Agent Scalability

`SkillOptFlow` batch_size=40 runs 40 concurrent `PlanActFlow` instances:
- ✅ Each flow has its own `ExecutorAgent`/`PlannerAgent` (no shared mutable state per agent)
- ⚠️ All 40 flows share the same SQLite write connection (serialized)
- ⚠️ All 40 flows publish to the same `AsyncEventBus` (serialized via `asyncio.Lock`)
- ⚠️ All 40 flows share one LLM adapter instance (rate-limited upstream)

Architecture is sound for asyncio but will hit API rate limits and DB write throughput before CPU.

---

## 6. Architectural Anti-Patterns

### 6.1 God Class — `mediator.py`

Contains the `Mediator` dispatcher PLUS `LoggingBehavior`, `ValidationBehavior` (duplicate), and `ValidationGateBehavior`, plus a mid-file `import asyncio` at line 361. A mediator file should contain only the dispatcher. The `behaviors/` subdirectory was created and populated but `mediator.py` was not cleaned up.

### 6.2 Hidden Monolith — Root Shim Layer

`weebot/` root contains 20+ legacy flat files that form an unstructured dependency hub shared between new and old code. Any change to these files has unknown blast radius across both layers simultaneously. The architecture fitness test acknowledges them as "allowed shims" in a carve-out list — a code smell for a temporary state that has persisted across phases.

### 6.3 Shared Database Coupling

All persistence components share `weebot_sessions.db`. Schema migrations for any one component (skills, trajectories, sessions) lock out all others. No per-domain database isolation.

### 6.4 Anemic CQRS Handler Side-Effects

`CreatePlanHandler` and `UpdatePlanHandler` execute business logic but do not save the resulting session state. The persistence side-effect exists only in `PlanActFlow._emit()`. Callers using the Mediator directly (tests, future integrations) get the logic but miss the persistence — a hidden invariant with no compile-time enforcement.

### 6.5 Temporal Coupling — Shared Mediator Mutation

`Container.build_skill_opt_flow()` adds the validation gate behavior to the shared singleton mediator. Multiple `build_skill_opt_flow()` calls (e.g., two parallel training runs) accumulate duplicate gates. The second `ApplySkillEditsCommand` runs validation twice, silently — a temporal dependency between construction order and runtime behavior.

### 6.6 Infrastructure Leakage into Application Services

`application/services/multi_source_research.py` imports `WebSearchTool` and `AdvancedBrowserTool` directly. There is no `BrowserPort` or `WebSearchPort` mediating this access, making the service impossible to test with substitutes or to swap implementations.

### 6.7 Premature Abstraction — Dead `ToolRepositoryPort`

`application/ports/tool_repository_port.py` defines a `ToolRepositoryPort` ABC and an implementing adapter exists — but no application code calls through it. Three tool files bypass it with direct SQLite. The port exists architecturally but is unused in production paths.

### 6.8 String-Based Command Routing in Pipeline Behavior

```python
# mediator.py:394
if cmd_name != "ApplySkillEditsCommand":
    return result
```

Uses string comparison instead of `isinstance(request, ApplySkillEditsCommand)`. If the command is renamed, the gate silently passes all commands without validation. This is fragile coupling via naming convention.

---

## 7. Refactoring Roadmap

### Phase A — Immediate Critical Fixes (1–2 days)

**A1. Fix domain purity violation**  
File: `weebot/domain/models/user_profile.py:21-23`  
Remove imports of `weebot.nlp_understanding`, `weebot.multi_source_research`, `weebot.information_synthesis`. Either define equivalent types inline within `domain/` or move `user_profile.py` to `weebot/application/` where the dependency direction is legal.

**A2. Fix importlinter contract to catch root-module violations from domain**  
File: `.importlinter` — `domain-purity` contract  
Add to `forbidden_modules`: `weebot.nlp_understanding`, `weebot.multi_source_research`, `weebot.information_synthesis`, `weebot.strategy_adaptation`, `weebot.source_credibility_assessment`, `weebot.external_service_integration`.

**A3. Extract behaviors from mediator.py**  
Move `LoggingBehavior`, `ValidationBehavior`, `ValidationGateBehavior` to `weebot/application/cqrs/behaviors/`. Delete the duplicate `ValidationBehavior` in `mediator.py`. Move `import asyncio` to the top of the file.

**A4. Fix ValidationGateBehavior string routing**  
Replace `if cmd_name != "ApplySkillEditsCommand"` with `isinstance` check after importing the command class.

---

### Phase B — High-Impact Structural Fixes (1–2 weeks)

**B1. Persist session state in CQRS handlers**  
`CreatePlanHandler.handle()` and `UpdatePlanHandler.handle()` must call `await self._state_repo.save_session(updated_session)` after successful plan operations. Otherwise the CQRS path silently skips persistence.

**B2. Scope a fresh Mediator per SkillOptFlow instance**  
`build_skill_opt_flow()` should construct a new `Mediator` for each flow rather than mutating the shared singleton. The new mediator inherits default behaviors but owns its own validation gate.

**B3. Fix application services' direct tool imports**  
`multi_source_research.py` should receive browser/search tools via constructor injection or define a `ResearchPort` ABC. Same pattern for `complex_task_executor.py` → `StrategyAdapter`.

**B4. Promote ToolCollection to application layer**  
`ToolCollection` has no infrastructure dependencies. Move it to `weebot/application/models/tool_collection.py` so application imports are intra-layer rather than cross-layer.

**B5. Wire EventStore by default**  
`di.py:configure_defaults()` should register `EventStorePort → EventStore` unconditionally. Audit log should be on by default.

---

### Phase C — Long-Term Architecture Evolution (1–3 months)

**C1. Eliminate root-level legacy shim layer**  
Complete migration of all root-level `weebot/*.py` files to their correct clean-arch location:

| Root file | Correct destination |
|---|---|
| `nlp_understanding.py` | `weebot/application/services/nlp_understanding.py` |
| `multi_source_research.py` | `weebot/application/services/multi_source_research.py` |
| `information_synthesis.py` | `weebot/application/services/information_synthesis.py` |
| `strategy_adaptation.py` | `weebot/application/services/strategy_adaptation.py` |
| `external_service_integration.py` | `weebot/infrastructure/adapters/external_services.py` |
| `state_coordinator.py` | Merge into `TaskRunner`, then delete |
| `agent_core_v2.py` | Delete (superseded by `PlanActFlow`) |

**C2. Split shared SQLite into per-domain databases**  
Separate `weebot_sessions.db` into `sessions.db` (session state), `skills.db` (skills + trajectories), and `cache.db` (response cache). For production scale: PostgreSQL + `asyncpg` with per-domain connection pools.

**C3. Introduce a durable task queue**  
Replace `TaskRunner`'s in-memory `asyncio.PriorityQueue` with Redis Streams or RabbitMQ for durable task delivery, multi-process deployment support, and dead-letter queue for failed sessions.

**C4. Type the `Session.context` dict**  
Define a `SessionContext(BaseModel)` with explicit typed fields for all known keys (`skill_name`, `skill_content`, `_original_task`, `facts: Dict[str, Any]`). Eliminates magic-string keys and enables validation.

**C5. Complete ToolConfig DI migration**  
Finish migrating `bash_tool.py`, `python_tool.py`, `powershell_tool.py`, `file_editor.py` to receive configuration via constructor injection instead of importing `WeebotSettings` directly.

**C6. Enable importlinter in CI as a merge gate**  
Run `lint-imports` as a CI step (not just in the fitness test suite). With the corrected contracts from A2, this converts architecture debt from "detected in tests with exceptions" to "blocked at merge."

---

### Migration Sequencing and Risk

```
A1 (domain purity) ──→ A2 (importlinter) ──→ A3 (mediator cleanup)
                                               ↓
B4 (ToolCollection)──→ B3 (services DI) ──→ B1 (CQRS persistence)
                                               ↓
B2 (scoped mediator) ──→ C3 (message queue) ──→ C2 (DB split) ──→ C1 (shim elimination)
```

| Phase | Duration | Risk | Test coverage needed |
|---|---|---|---|
| A | 1–2 days | Low (import-only changes) | Re-run `test_architecture_fitness.py` |
| B | 1–2 weeks | Medium (adds persistence side-effects to handlers) | New integration tests for CQRS persistence |
| C | 1–3 months | High (infrastructure replacement, migration scripts) | Full integration + load tests |

---

## 8. Confidence Assessment

### Verified Findings (confirmed by direct code reading)

- ✅ Domain purity violation in `user_profile.py` (lines 21–23, confirmed)
- ✅ Duplicate `ValidationBehavior` (mediator.py:322 vs behaviors/validation.py:7, confirmed)
- ✅ `import asyncio` mid-file in mediator.py (line 361, confirmed)
- ✅ `ValidationGateBehavior` string comparison routing (mediator.py:394, confirmed)
- ✅ `multi_source_research.py` direct tool imports (lines 22–24, confirmed)
- ✅ `complex_task_executor.py` importing root shims (lines 26, confirmed)
- ✅ `workflow_planner.py` importing root shims (line 12, confirmed)
- ✅ Architecture fitness test carve-out lists (settings_exceptions, known_exception_tools, confirmed)
- ✅ No `state_repo.save_session()` in `CreatePlanHandler` or `UpdatePlanHandler` (handlers.py read, confirmed)
- ✅ `mediator.add_pipeline_behavior(gate)` on shared singleton (di.py:457, confirmed)
- ✅ Circular import test is `@pytest.mark.skip` (test_architecture_fitness.py:491, confirmed)
- ✅ `EventStorePort` not registered in `configure_defaults()` (di.py read, confirmed)
- ✅ `PlanActFlow.max_iterations=50` hardcoded (plan_act_flow.py:170, confirmed)
- ✅ `.importlinter` contract does not include root-level shims in forbidden list (confirmed)
- ✅ `baseline_score=None` hardcoded in `ValidationGateBehavior` (mediator.py:415, confirmed)

### Hypothesis Findings (structurally certain, not fully traced)

- ⚠️ Calling `build_skill_opt_flow()` twice accumulates duplicate behaviors on the shared mediator — structurally certain from singleton + append semantics, not traced through a live test
- ⚠️ `Session.context["facts"]` grows unboundedly — no eviction logic found in any session management code; confirmed by absence
- ⚠️ `SessionMemory` in-process lookup index is reset on deserialization — structurally certain from the `PrivateAttr` not being serialised by Pydantic

### Areas Lacking Sufficient Evidence

- ❓ `weebot/core/workflow_orchestrator.py` contents not fully read — unclear whether it duplicates `PlanActFlow` functionality
- ❓ `weebot/application/cqrs/handlers/query_handlers.py` handler coverage not fully audited
- ❓ `weebot/agents/` persona system integration depth with clean-arch flows
- ❓ Whether `test_domain_has_no_outer_imports` currently passes or fails given `user_profile.py` violation
- ❓ `weebot/GitNexus-main/` vendored dependency interaction surface (excluded from scope)
- ❓ `weebot-ui/` TypeScript frontend (excluded from scope)

---

*Produced via static analysis: direct file reads, AST import tracing, cross-module dependency mapping, and fitness test inspection. No runtime execution performed.*
