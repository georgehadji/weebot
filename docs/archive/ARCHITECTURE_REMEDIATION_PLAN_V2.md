# Architecture Remediation Plan V2

**Generated:** 2026-06-11  
**Source:** Architecture Audit V2 (EGFV protocol)  
**Score:** 6/10  
**Urgency:** Next Sprint  

---

## Summary of Findings

| Category | Count | Critical | High | Medium |
|----------|-------|----------|------|--------|
| Layer violations (imports) | 16 | 2 | 8 | 6 |
| God modules | 3 | 0 | 3 | 0 |
| Unbound ports (typed) | ~27 | – | 27 | – |
| Legacy root shims | 6 | 0 | 2 | 4 |
| Ports registered as string keys | ~22 | 0 | 0 | 22 |
| Circular dependency paths | 2 | 2 | 0 | 0 |

---

## IMMEDIATE (fix before next feature)

### I1. Fix `infrastructure/interface_customization.py` → `application.services.profile_manager`

**Finding:** Line 20 directly imports `UserProfileManager` from application services.  
**Violation:** CRITICAL — infrastructure must depend on ports, not application services.  
**Action:**

```python
# In infrastructure/interface_customization.py:
# REMOVE:
from weebot.application.services.profile_manager import UserProfileManager

# ADD: Use ProfileStoragePort (already defined at application/ports/profile_storage_port.py)
# The adapter should accept ProfileStoragePort via constructor injection.
```

**Specific steps:**
1. Inject `ProfileStoragePort` into `InterfaceCustomizationService.__init__` instead of importing `UserProfileManager`
2. Register a profile storage adapter in DI container
3. Remove the top-level `from weebot.application.services.profile_manager import UserProfileManager`
4. Run `import-linter` to verify the contract heals

**Expected outcome:** `weebot.infrastructure → weebot.application.services` violation count dropped to 5.

---

### I2. Fix `infrastructure/adapters/sub_agent_factory.py` → `application.flows` + `application.di`

**Finding:** Lines 164-165 import `PlanActFlow` and `Container` from application layer.  
**Violation:** CRITICAL — infrastructure should not construct flows or DI containers. This creates a circular dependency: `infra → app → infra`.  
**Action:**

```python
# In sub_agent_factory.py _build_flow method:
# REMOVE:
from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.di import Container

# REPLACE WITH: accept a factory callable or Mediator in __init__
# class SubAgentFactory:
#     def __init__(self, flow_factory: Callable[[Session, SubAgentSpec], PlanActFlow]):
#         self._flow_factory = flow_factory
```

**Specific steps:**
1. Add `FlowFactoryPort` or use existing `SubAgentFactoryPort` with a `build_flow` method
2. Implement the flow-building logic in a _factory class in `application/flows/factories/`_
3. Inject via DI container — the composition root wires the flow building, not the adapter
4. Remove the deferred imports from `sub_agent_factory.py`

**Expected outcome:** Circular infra↔app dependency eliminated.

---

### I3. Fix `core/bash_guard.py` → `infrastructure.observability.metrics`

**Finding:** Line 366 imports `from weebot.infrastructure.observability import metrics` inside a function.  
**Violation:** HIGH — core must not depend on infrastructure. The metrics call is try/except-guarded but still creates a hidden coupling.  
**Action:**

```python
# In core/bash_guard.py:
# REMOVE:
from weebot.infrastructure.observability import metrics as _m
_m.bash_guard_events_total.labels(risk_level=max_risk.value).inc()

# REPLACE WITH: callback injection
# class BashGuard:
#     def __init__(self, on_security_event: Optional[Callable[[RiskLevel], None]] = None):
#         self._on_security_event = on_security_event or (lambda r: None)
# Then in evaluation: self._on_security_event(max_risk)
```

**Specific steps:**
1. Add an `on_security_event` callback parameter to `BashGuard.__init__`
2. Wire the Prometheus counter from the DI container or interface layer
3. Remove the deferred import

**Expected outcome:** Core layer becomes infrastructure-free.

---

### I4. Fix interfaces importing infrastructure directly (9 violations)

**Files requiring fixes:**  
- `interfaces/factories.py:174` — `from weebot.infrastructure.mcp.mcp_toolkit_adapter import MCPToolkitAdapter`  
- `interfaces/web/main.py:242` — `from weebot.infrastructure.observability.prometheus_adapter import PrometheusMetricsAdapter`  
- `interfaces/web/routers/health.py:119,192,253,269` — multiple direct infra imports  
- `interfaces/windows_toast_subscriber.py:18,28`  
- `interfaces/windows/__init__.py:22`  

**Action:** Route all infrastructure dependencies through the DI container.  

**Specific steps:**
1. `factories.py`: Inject `MCPToolkitAdapter` via constructor parameter instead of direct import
2. `web/main.py`: Move metrics endpoint to use `MetricsPort` from DI, not direct `PrometheusMetricsAdapter`
3. `health.py`: Extract health check logic into an application service; inject via DI
4. Verify `.importlinter` contract `interfaces-no-infra` passes

**Expected outcome:** All interface-layer files depend only on `application` and `domain`.

---

## HIGH-IMPACT (next sprint)

### H1. Decompose `ExecutorAgent` (God module — 1,124 lines, 28 methods, 23 imports)

**Finding:** Single class with 28 methods spanning cascade logic, retry, tool loops, context management, token budgets, and error classification.  
**Action:** Extract 3-4 focused classes.

**Proposed decomposition:**
```
application/agents/
├── executor.py                    # Orchestrator (~250 lines) — delegates to specialized services
├── executor/
│   ├── __init__.py
│   ├── cascade_manager.py         # Model cascade, retry, circuit breaker
│   ├── tool_loop.py               # Tool execution loop, result validation
│   ├── context_builder.py         # Prompt construction, memory compaction
│   └── step_controller.py         # Step budget, repetition detection
```

**Migration steps:**  
1. Copy `executor.py` to `executor/__init__.py` as a thin re-export shell
2. Extract `CascadeManager` class — move all model fallback/retry logic
3. Extract `ToolLoop` class — move all tool dispatch, result handling
4. Extract `ContextBuilder` class — move all prompt/memory construction
5. Extract `StepController` class — move step budget, repetition detection
6. Update all importers to use new submodules
7. Delete old `executor.py` when no references remain

**Risk:** High. The executor is central to all agent flows. Test after each extraction. Requires QA run of PlanActFlow before merging.

---

### H2. Decompose `model_selection.py` (God module — 3,266 lines)

**Finding:** Contains model configs, selection strategies, cost tracking, routing — 4+ responsibilities in a single file.  
**Action:** Split into a package.

**Proposed decomposition:**
```
application/services/
├── model_selection/
│   ├── __init__.py                # Re-exports public API
│   ├── config.py                  # ModelConfig dataclass, ModelTier enum
│   ├── registry.py                # Model registry — all model definitions
│   ├── strategy.py                # ModelSelectionStrategyABC + implementations
│   ├── selector.py                # ModelSelector orchestrator
│   └── cost_tracker.py            # Cost tracking, budget enforcement
```

**Migration steps:**  
1. Extract `ModelConfig` and `ModelTier` into `model_selection/config.py`
2. Extract model definitions into `model_selection/registry.py` (split by provider)
3. Extract strategies into `model_selection/strategy.py`
4. Keep the public facade in `model_selection/__init__.py`
5. Update all importers

**Risk:** Medium. Model selection is consumed by many services but mostly through the public API surface.

---

### H3. Decompose `infrastructure/interface_customization.py` (1,210 lines)

**Finding:** Infrastructure file importing from application services, containing UI/theme logic that belongs in application or interface layer.  
**Action:** Split by concern and fix the layer violation.

**Proposed decomposition:**
```
infrastructure/
├── customization/
│   ├── __init__.py
│   ├── theme_repository.py        # Theme persistence (infra only)
│   └── profile_adapter.py         # Adapter for ProfileStoragePort (infra only)

application/services/
├── customization_service.py       # UI customization use cases (app layer)

interfaces/
├── web/routers/customization.py   # REST endpoints (interface layer)
```

**Migration steps:**  
1. Extract pure infrastructure concerns (theme storage, I/O) to `infrastructure/customization/`
2. Move business logic (preference aggregation, theme selection) to `application/services/customization_service.py`
3. Move HTTP/API concerns to `interfaces/web/`
4. Remove the layer-violating import of `application.services.profile_manager`
5. Register adapters in DI container

**Risk:** Medium. The module is used by existing web endpoints and migration requires coordinated changes.

---

### H4. Bind all untyped string-key registrations as typed ports

**Finding:** 22 string-key registrations (e.g., `"activity_stream"`, `"code_reviewer"`, `"skill_retriever"`) bypass the type-safe `Container.get(SomePort)` contract.  
**Action:** Create proper port interfaces for each string-keyed binding and register by type.

**Priority list:**  
1. `"code_reviewer"` → Already has `CodeReviewerPort` — change registration to typed
2. `"dreamer_agent"` → Already has `DreamerPort` — change registration to typed
3. `"intent_review"` → Already has `IntentReviewPort` — change registration to typed
4. `"main_review"` → Already has `MainReviewPort` — change registration to typed
5. `"trust_report_service"` → Already has `TrustReportPort` — change registration to typed
6. `"retention_agent"` → Already has `RetentionAgentPort` — change registration to typed
7. `"skill_retriever"` → Already has `SkillRetrieverPort` — change registration to typed
8. `"knowledge_graph"` → Already has `KnowledgeGraphPort` — change registration to typed
9. `"behavioral_learner"` → Already has `BehavioralLearnerPort` — change registration to typed
10. `"optimizer_port"` → Already has `OptimizerPort` — change registration to typed

**Remaining** (`"session_persistence"`, `"activity_stream"`, `"response_cache"`, `"personality"`, `"structured_logger"`, `"cascade_tracker"`, `"soul_provider"`, `"idea_gate"`, `"scheduler"`, `"skill_curator"`, `"opportunity_engine"`, `"browser_inspector_tool"`, `"dispatch_agents_tool"`, `"workflow_orchestrator_tool"`): Create port interfaces or integrate into existing ports.

**Risk:** Low for ports that already have interfaces; Medium for those without.

---

### H5. Increase test coverage from 4.9% to ≥25%

**Finding:** 26 test files for 535 source files (4.9% file coverage). The architecture fitness test suite (`test_architecture_fitness.py`) reports 150 pass/0 fail/41 skipped — the 41 skipped ports mean 41 of 49 ports lack contract tests.  
**Action:**

1. **Port contract tests** (highest ROI): Write one test per unbound port verifying it can be registered and resolved from DI container — ~27 new tests
2. **Layer boundary tests**: Add AST-based tests for each known violation file → ~10 new tests
3. **Critical path tests**: Write integration test for `PlanActFlow` full cycle (Planning → Executing → Summary) with mock LLM → ~3 new tests
4. **God module tests**: Write focused unit tests for each extracted submodule during decomposition → ~15 new tests

**Target:** 55 test files (+29). Coverage: 55/535 = ~10%. Next target: 25% (134 files).

---

## LONG-TERM (architectural evolution)

### L1. Target-state architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        interfaces/                                    │
│  (CLI, Web/FastAPI, MCP, Discord, Slack, Telegram, Windows)           │
│  ─── depends on application only (NO direct infrastructure import)    │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        application/                                   │
│  flows/ | agents/ | services/ | cqrs/ | skills/                       │
│  ─── depends on domain + core (NO infrastructure dependency)          │
│  ─── di/ is the ONLY composition root (imports infrastructure)        │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        domain/                                        │
│  models/ | services/ | ports.py                                       │
│  ─── pure Python + stdlib (ZERO outer-layer imports)                 │
│  ─── 45 models, 5 Protocol ports                                     │
└──────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │
┌──────────────────────────────────────────────────────────────────────┐
│                        infrastructure/                                │
│  adapters/ | persistence/ | sandbox/ | llm/ | browser/                │
│  ─── depends on domain + application/ports only                      │
│  ─── NO dependency on application/agents, flows, services, cqrs, di   │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                        core/                                          │
│  bash_guard/ | circuit_breaker/ | error_classifier/                   │
│  ─── depends on stdlib + external libs only                          │
│  ─── NO dependency on application, infrastructure, or interfaces      │
│  ─── communicates via injected callbacks / Protocols                  │
└──────────────────────────────────────────────────────────────────────┘
```

### L2. Migration sequence with dependency ordering

| Step | Depends On | Effort | Risk |
|------|-----------|--------|------|
| 1. Fix I1 (interface_customization profile import) | None | 1 day | Low |
| 2. Fix I2 (sub_agent_factory circular dep) | None | 1 day | Medium |
| 3. Fix I3 (bash_guard metrics callback) | None | 0.5 day | Low |
| 4. Fix I4 (interfaces direct infra imports) | None | 2 days | Medium |
| 5. H4 (type-safe port bindings) | None | 2 days | Low |
| 6. Infrastructure cleanup (remove app dependencies) | 1, 2 | 1 day | Low |
| 7. H1 (decompose executor.py) | 6 | 3 days | High |
| 8. H2 (decompose model_selection.py) | 6 | 2 days | Medium |
| 9. H3 (decompose interface_customization.py) | 1, 6 | 2 days | Medium |
| 10. H5 (test coverage expansion) | 7, 8, 9 | 5 days | Low |
| 11. Delete legacy root shims | 5, 10 | 1 day | Low |
| 12. Run import-linter in CI as blocking gate | 1-11 | 0.5 day | Low |
| 13. Update ARCHITECTURE.md with accurate score | 1-12 | 0.5 day | None |

**Total estimated effort:** 19 days  
**Parallelization:** Steps 1-5 can run in parallel. Steps 7-9 require step 6.

### L3. Risk per migration step

| Step | Risk | Mitigation |
|------|------|-----------|
| 1 (interface_customization) | Low — isolated change, no callers depend on direct profile import | Test after each edit |
| 2 (sub_agent_factory) | **Medium** — SubAgentFactory is used by multiple agent flows | Create integration test before/after |
| 3 (bash_guard) | Low — API-compatible change with default callback | Add unit test for callback injection |
| 4 (interfaces importing infra) | Medium — touches web routes that may have no test coverage | Manual smoke test of /health, /metrics endpoints |
| 5 (type-safe ports) | Low — mechanical replacement, compiler-checked | Verify all Container.get() calls compile |
| 6 (infra cleanup) | Low — remove already-dead imports after steps 1-2 | Run full test suite |
| 7 (executor decomposition) | **Highest risk** — central to all agent execution | Ship in 4 separate PRs, each with integration test |
| 8 (model_selection split) | Medium — many importers but public API stable | Keep re-export shell during migration |
| 9 (interface_customization split) | Medium — UI configuration used by web endpoints | Manual QA on UI customization features |
| 10 (test expansion) | Low — additive only | No migration risk |
| 11 (delete legacy) | Medium — must verify zero remaining callers | grep all imports before deletion |
| 12 (CI blocking gate) | Low — config change only | Verify current CI passes with new linter rules |
| 13 (doc update) | Low — docs only | N/A |

---

## Switching Triggers

| Condition | Required Architecture Change |
|-----------|------------------------------|
| >10 concurrent users | PostgreSQL migration (SQLite write serialization ceiling) |
| Multi-process deployment | Redis/RabbitMQ task queue + distributed event bus |
| >100 tool definitions | Enforce `ToolRepositoryPort` for all tool access |
| Cross-session agent communication | `SwarmEventBusPort` → dedicated message broker |
| Compliance/audit requirements | Durable `EventStorePort` with audit log export |

---

## Acceptance Criteria

The plan is complete when:

- [ ] `import-linter` passes all 5 contracts with zero violations
- [ ] `core/bash_guard.py` has zero imports from `weebot.application`, `weebot.infrastructure`, or `weebot.interfaces`
- [ ] `infrastructure/` has zero imports from `weebot.application.agents`, `.flows`, `.services`, `.cqrs`, or `.di`
- [ ] `interfaces/` has zero imports from `weebot.infrastructure` or `weebot.tools`
- [ ] `domain/` has zero imports from `weebot.application`, `.infrastructure`, `.interfaces`, `.core`, `.tools`
- [ ] All 49 port interfaces have at least one registered DI binding
- [ ] All DI registrations use typed ports, not string keys
- [ ] `ExecutorAgent` broken into ≥4 focused modules, each ≤400 lines
- [ ] `model_selection.py` broken into structured package, no single file ≥500 lines
- [ ] `interface_customization.py` split into proper layers with zero layer violations
- [ ] Test file count ≥55 (10% file coverage minimum)
- [ ] Legacy root shims (state_manager.py, state_coordinator.py, ai_router.py, etc.) verified zero active callers and removed
- [ ] ARCHITECTURE.md score updated to reflect actual state (target: 8/10 post-remediation)

---

## Appendix: Layer Violation Inventory (verified)

| File | Line | Violation | Severity | Ticket |
|------|------|-----------|----------|--------|
| `infrastructure/interface_customization.py` | 20 | `from weebot.application.services.profile_manager import UserProfileManager` | CRITICAL | I1 |
| `infrastructure/adapters/sub_agent_factory.py` | 164-165 | `from weebot.application.flows.plan_act_flow import PlanActFlow` / `from weebot.application.di import Container` | CRITICAL | I2 |
| `core/bash_guard.py` | 366 | `from weebot.infrastructure.observability import metrics as _m` | HIGH | I3 |
| `interfaces/factories.py` | 174 | `from weebot.infrastructure.mcp.mcp_toolkit_adapter import MCPToolkitAdapter` | HIGH | I4 |
| `interfaces/web/main.py` | 242 | `from weebot.infrastructure.observability.prometheus_adapter import PrometheusMetricsAdapter` | MEDIUM | I4 |
| `interfaces/web/routers/health.py` | 119 | `from weebot.infrastructure.observability.health_service import ...` | MEDIUM | I4 |
| `interfaces/web/routers/health.py` | 192 | `from weebot.infrastructure.observability.prometheus_adapter import ...` | MEDIUM | I4 |
| `interfaces/web/routers/health.py` | 253 | `from weebot.infrastructure.mcp.mcp_health import ...` | MEDIUM | I4 |
| `interfaces/web/routers/health.py` | 269 | `from weebot.infrastructure.observability.lifespan import ...` | MEDIUM | I4 |
| `interfaces/windows_toast_subscriber.py` | 18,28 | `from weebot.infrastructure.adapters.windows_desktop import ...` | MEDIUM | I4 |
| `interfaces/windows/__init__.py` | 22 | `from weebot.infrastructure.adapters.windows_desktop import ...` | MEDIUM | I4 |
| `infrastructure/adapters/sandbox_backend_adapter.py` | 53 | `from weebot.application.services.plan_history import PlanHistory` | HIGH | I2 (follow-up) |
| `infrastructure/notifications/windows_toast.py` | 231 | `from weebot.application.services.plan_history import PlanHistory` | MEDIUM | I2 (follow-up) |
| `infrastructure/interface_customization.py` | 1144 | `from weebot.application.services.plan_history import PlanHistory` | MEDIUM | I1 (follow-up) |

## Appendix: String-Key DI Registrations (22 total)

These bypass type-safe `Container.get()` and should be migrated to typed port bindings:

| String Key | Existing Port Interface? | Priority |
|-----------|-------------------------|----------|
| `code_reviewer` | ✅ CodeReviewerPort | Immediate |
| `dreamer_agent` | ✅ DreamerPort | Immediate |
| `intent_review` | ✅ IntentReviewPort | Immediate |
| `main_review` | ✅ MainReviewPort | Immediate |
| `trust_report_service` | ✅ TrustReportPort | Immediate |
| `retention_agent` | ✅ RetentionAgentPort | Immediate |
| `skill_retriever` | ✅ SkillRetrieverPort | Immediate |
| `knowledge_graph` | ✅ KnowledgeGraphPort | Immediate |
| `behavioral_learner` | ✅ BehavioralLearnerPort | Immediate |
| `optimizer_port` | ✅ OptimizerPort | Immediate |
| `session_persistence` | ❌ No port | Sprint |
| `activity_stream` | ❌ No port | Sprint |
| `response_cache` | ❌ No port | Sprint |
| `personality` | ❌ No port | Sprint |
| `structured_logger` | ❌ No port | Sprint |
| `cascade_tracker` | ❌ No port | Sprint |
| `soul_provider` | ❌ SoulProviderPort exists in `application/ports/soul_provider_port.py` | Immediate |
| `idea_gate` | ❌ No port | Sprint |
| `scheduler` | ❌ No port | Sprint |
| `skill_curator` | ❌ No port | Sprint |
| `opportunity_engine` | ❌ No port | Sprint |
| `kg_adapter` | ❌ No port | Sprint |

## Appendix: God Module Metrics

| Module | Lines | KB | Classes | Methods | Responsibilities |
|--------|-------|----|---------|---------|-----------------|
| `application/agents/executor.py` | 1,124 | 52 | 1 | 28 | Cascade, retry, tool dispatch, context, tokens, budget, error classification |
| `application/services/model_selection.py` | 3,266 | 140 | ~15 | ~50 | Configs, routing, strategies, cost tracking, budget, model definitions |
| `infrastructure/interface_customization.py` | 1,210 | 47 | ~8 | ~40 | Theme management, profile I/O, UI config persistence |

## Appendix: Legacy Root Shims (6 files)

| File | Lines | Deprecation Banner | Active Callers? | Sunset |
|------|-------|-------------------|----------------|--------|
| `weebot/state_manager.py` | 656 | ✅ "Frozen. No new features." | Yes (state_coordinator imports it) | 2027-03-01 |
| `weebot/state_coordinator.py` | 230 | ✅ "Bucket D — Freeze" | Yes (imported by some agents) | 2026-09-01 |
| `weebot/ai_router.py` | 57 | ✅ "Compatibility shim" | Yes (agent_core_v2 imports it) | 2027-03-01 |
| `weebot/agent_core_v2.py` | 360 | ✅ "Legacy frozen" | Yes (old tests) | 2027-03-01 |
| `weebot/nlp_understanding.py` | 772 | ❌ No banner | Unknown | None set |
| `weebot/notifications.py` | 1563 | ❌ No banner | Unknown | None set |
