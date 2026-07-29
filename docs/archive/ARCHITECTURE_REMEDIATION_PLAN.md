# Architecture Remediation Plan: 6/10 → 9/10

**Baseline:** Architecture Audit v2 (2026-06-18) — score 6/10
**Target:** ≥9/10
**Owner:** Weebot Engineering
**Status:** Draft

---

## Score Breakdown & Gap Analysis

| Dimension | Current | Target | Gap |
|---|---|---|---|
| Layer Separation | 7/10 | 10/10 | Application→Infrastructure leakage (38+ violations) |
| Abstraction Discipline | 4/10 | 9/10 | 86% port bloat (47/54 ports with 0-1 impls) |
| Module Cohesion | 5/10 | 9/10 | God executor class (1,414 lines), god handlers file (779 lines) |
| Coupling Control | 6/10 | 9/10 | DI singleton, mutable globals, direct file/env access |
| Async Hygiene | 9/10 | 9/10 | Already solid — no changes needed |
| Failure Semantics | 9/10 | 10/10 | Already solid — observability gap only |
| Testability | 6/10 | 9/10 | Singleton container, concrete repo imports block isolation |
| Scalability Readiness | 5/10 | 8/10 | SQLite ceiling identified, PostgreSQL scaffolded but not default |

---

## Phase 1: Critical Remediation (Weeks 1-2)

### Goal: Eliminate the three CRITICAL findings. No new features during this phase.

---

### Step 1.1 — Extract `ExecutorAgent` into focused collaborators

**Target:** `weebot/application/agents/executor/_base.py` (1,414 lines → ~400 line orchestrator + 3 collaborators)

**Extraction plan:**

| New Module | Lines | Responsibility | Extracted From |
|---|---|---|---|
| `application/agents/executor/_cascade.py` | ~300 | `_call_with_cascade`, `_cascade_try_chat`, `_try_live_model_rescue`, `_parallel_probe_models`, `_sequential_fallback` | `_base.py:616-674` |
| `application/agents/executor/_tool_invoker.py` | ~200 | `_execute_tool_call`, `_validate_tool_result`, `_resolve_tool`, tool concurrency gating | `_base.py:780-940` |
| `application/agents/executor/_error_handler.py` | ~150 | `_classify_error`, `_is_retryable`, `_should_fail_fast`, error→recovery routing | `_base.py:950-1050` |
| `application/agents/executor/_context_compressor.py` | ~150 | `_compress_conversation`, `_summarize_step`, `_reflect_on_screenshot` | `_base.py:1050-1200` |

**`_base.py` after extraction:** ~400 lines. Retains `execute_step()` as the orchestrator that delegates to the four collaborators. Collaborators receive dependencies via constructor injection, not via the executor instance.

**Verification:**
- `pytest tests/unit/test_executor*.py tests/unit/test_cascade*.py -v` — all existing executor tests pass
- `wc -l weebot/application/agents/executor/_base.py` ≤ 450
- Each new module ≤ 350 lines
- Architecture fitness test: no new imports of `_base.py` internals cross-layer

**Risk:** MEDIUM — behavioral refactor. Mitigation: extract collaborators one at a time, run full test suite between each.

---

### Step 1.2 — Delete zero-implementation ports

**Target:** 21 port files in `weebot/application/ports/` with zero concrete implementations.

**Delete list:**

```
application/ports/audit_port.py
application/ports/behavioral_learner_port.py
application/ports/canonicalizer_port.py
application/ports/capability_gate_port.py
application/ports/code_reviewer_port.py
application/ports/dreamer_port.py
application/ports/hook_registry_port.py              # if exists
application/ports/icontext_engine_port.py             # if exists
application/ports/igateway_session_store_port.py      # if exists
application/ports/intent_review_port.py
application/ports/judge_port.py
application/ports/main_review_port.py
application/ports/optimizer_port.py
application/ports/plan_critic_port.py
application/ports/retention_agent_port.py
application/ports/self_improvement_port.py
application/ports/skill_retriever_port.py
application/ports/step_evaluator_port.py
application/ports/task_router_port.py
application/ports/trust_report_port.py
application/ports/truth_binding_port.py
```

**Before deleting each file:**
1. `search_content "from weebot.application.ports.{name} import"` — confirm zero callers
2. `search_content "from weebot.application.ports.{name}"` — confirm zero callers
3. Check `application/di/` for any registration
4. Delete file
5. Run `pytest tests/unit/test_port_contracts.py tests/unit/test_architecture_fitness.py -v`

**Verification:**
- All architecture fitness tests pass
- `ls weebot/application/ports/*.py | wc -l` ≤ 37 (down from 58)
- No import errors on `python -c "from weebot.application.di import Container; Container().configure_defaults()"`

**Risk:** LOW — zero callers by definition. Only risk is undiscovered dynamic imports (unlikely; `search_content` catches these).

---

### Step 1.3 — Fix application→infrastructure leakage in flows and CQRS handlers

**Target:** 6 files importing concrete infrastructure repos at runtime.

| File | Current Import | Replace With |
|---|---|---|
| `flows/skill_opt_flow.py:36-37` | `from weebot.infrastructure.persistence.skill_store import SkillStore` + `TrajectoryRepository` | Inject `SkillIndexPort` + `TrajectoryRepositoryPort` via constructor |
| `flows/harness_opt_flow.py:39` | `from weebot.infrastructure.persistence.trajectory_repo import TrajectoryRepository` | Inject `TrajectoryRepositoryPort` via constructor |
| `cqrs/handlers/failure_signature_handlers.py:35` | `from weebot.infrastructure.persistence.trajectory_repo import TrajectoryRepository` | Inject `TrajectoryRepositoryPort` |
| `cqrs/handlers/skill_edit_handler.py:12` | `from weebot.infrastructure.persistence.skill_store import SkillStore` | Inject `SkillIndexPort` |
| `cqrs/handlers/trajectory_handler.py:22` | `from weebot.infrastructure.persistence.trajectory_repo import TrajectoryRepository` | Inject `TrajectoryRepositoryPort` |
| `cqrs/handlers/transfer_handler.py:47` | `from weebot.infrastructure.persistence.skill_store import SkillStore` | Inject `SkillIndexPort` |

**For each:**
1. Verify the target port exists in `application/ports/` and has required methods
2. If missing methods, add them to the port ABC
3. Change the handler constructor to accept the port (not the concrete class)
4. Update DI registrations in `application/di/` to wire the concrete adapter
5. Run affected tests

**Verification:**
- `search_content "from weebot\.infrastructure\.persistence" --path weebot/application/flows` returns zero non-`TYPE_CHECKING` matches
- `search_content "from weebot\.infrastructure\.persistence" --path weebot/application/cqrs` returns zero non-`TYPE_CHECKING` matches
- All flow and CQRS handler tests pass

**Risk:** LOW — ports already exist, just need wiring changes.

---

## Phase 2: High-Impact Cleanup (Weeks 3-4)

### Goal: Resolve HIGH-severity findings. Rationalize the port surface.

---

### Step 2.1 — Consolidate single-implementation ports

**Target:** 27 ports with exactly one implementation. The rule: keep as a port **only if** polymorphism is planned within 6 months (per `ARCHITECTURE.md` scaling triggers or roadmap).

**Keep as ports (polymorphism planned):**

| Port | Reason |
|---|---|
| `LLMPort` | 4 implementations today (OpenRouter, Anthropic, OpenAI, DeepSeek, Moonshot) |
| `SandboxPort` | 4 implementations (NativeWindows, WSL2, DockerLinux, Modal) |
| `StateRepositoryPort` | 3 implementations (SQLite, PostgreSQL scaffolded, in-memory for tests) |
| `NotificationPort` | 3 implementations (Telegram, WindowsToast, SSE) |
| `ScoringPort` | 3 implementations (ExactMatch, Execution, Verifier) |
| `SkillIndexPort` | 3 implementations |
| `KnowledgeGraphPort` | 2 implementations |
| `AnalyticsSinkPort` | 2 implementations |

**Consolidate to concrete classes (no planned polymorphism):**

| Port | Merge Adapter Into |
|---|---|
| `BackendPort` → | Delete port; use `ConfigAdapter` directly |
| `BrowserPort` → | Delete port; use `PlaywrightAdapter` directly |
| `CheckpointPort` → | Delete port; use `SQLiteCheckpointStore` directly |
| `ConfigPort` → | Delete port; use `ConfigAdapter` directly |
| `DesktopPort` → | Delete port; use adapter directly |
| `EventBusPort` → | **KEEP** — polymorphic when swarm/Redis bus activates |
| `EventStorePort` → | **KEEP** — polymorphic when durable store activates |
| `MCPToolPort` → | Delete port; use `MCPClientManager` directly |
| `MemoryPort` → | Delete port; use `FilesystemMemoryAdapter` directly |
| `MetricsPort` → | Delete port; use `PrometheusAdapter` directly |
| `MisalignmentJournalPort` → | Delete port; use `SQLiteMisalignmentJournal` directly |
| `ProfileStoragePort` → | Delete port; use adapter directly |
| `RagPort` → | Delete port; use adapter directly |
| `RerankPort` → | Delete port; use `OpenRouterRerankAdapter` directly |
| `SkillVariantStorePort` → | Delete port; use `SkillVariantStore` directly |
| `SoulProviderPort` → | Delete port; use `FileSystemSoulProvider` directly |
| `SpeechPort` → | Delete port; use `WhisperSpeechAdapter` directly |
| `SteeringPort` → | Delete port; use `SteeringAdapter` directly |
| `SubAgentCostTrackerPort` → | Delete port; use `SubAgentCostTracker` directly |
| `SubAgentFactoryPort` → | Delete port; use `SubAgentFactory` directly |
| `SummaryRepositoryPort` → | Delete port; use `SQLiteSummaryRepo` directly |
| `SwarmEventBusPort` → | **KEEP** — polymorphic when swarm activates |
| `TaskQueuePort` → | Delete port; use in-memory queue directly |
| `ToolDiscoveryPort` → | Delete port; use `ToolDiscoveryAdapter` directly |
| `ToolRepositoryPort` → | **KEEP** — >100 tools triggers polymorphism |
| `TracingPort` → | Delete port; use `TracingAdapter` directly |

**Consolidation procedure (per port):**
1. Move any interface-level documentation from the port ABC to the concrete adapter
2. Update all importers: `from weebot.application.ports.X import XPort` → `from weebot.infrastructure.adapters.Y import YAdapter`
3. Remove port ABC file
4. Remove DI registration of port → adapter; register adapter directly as singleton
5. Run `pytest tests/unit/test_port_contracts.py tests/unit/test_architecture_fitness.py -v`
6. Update `.importlinter` contracts if port was in a contract

**Verification:**
- `ls weebot/application/ports/*.py | wc -l` ≤ 15 (down from ~37 after Phase 1)
- Every remaining port has ≥2 concrete implementations (searchable)
- All tests pass
- DI container configuration still produces a working system

**Risk:** MEDIUM — many import paths change. Mitigation: use `search_content` to find every importer before consolidation; batch by port to keep each commit small.

---

### Step 2.2 — Fix core layer boundary violations

**Target:** 5 core modules importing from application or infrastructure.

| File | Current Import | Fix |
|---|---|---|
| `core/trust_boundary.py:12` | `from weebot.application.ports.llm_port import LLMPort` | Move LLMPort reference to a Protocol defined in core or accept TYPE_CHECKING guard |
| `core/model_cascade_config.py:14` | `from weebot.application...` | Extract cascade config types to domain or accept TYPE_CHECKING |
| `core/approval.py:15` | `from weebot.infrastructure...` | Inject the dependency instead of importing |
| `core/error_classifier.py` (if exists) | infra import | Accept TYPE_CHECKING or inject |

**For each:**
1. If the import is type-only, wrap in `TYPE_CHECKING`
2. If it's a runtime dependency, inject it via constructor
3. If it's configuration, move the config types to `weebot/config/` (which is cross-cutting)
4. Run `pytest tests/unit/test_architecture_fitness.py -v`

**Verification:**
- Architecture fitness test for core layer passes with zero violations
- `search_content "from weebot\.(application|infrastructure|interfaces)" --path weebot/core` returns only TYPE_CHECKING-guarded imports

**Risk:** LOW — mostly adding `TYPE_CHECKING` guards or moving type definitions.

---

### Step 2.3 — Eliminate shared mutable state risks

**Target:** 4 module-level mutable state hotspots.

| Location | Current State | Fix |
|---|---|---|
| `utils/rate_limiter.py:94-95` | `_rate_limit_buckets: Dict[str, TokenBucket] = {}` | Add `reset_all_buckets()` function; call in `conftest.py` fixture teardown; document that tests must reset |
| `application/di/__init__.py:109-113` | `Container.get_static()` class-level singleton | Refactor `_cascade_try_chat` to receive dependencies via parameter; remove `get_static()` |
| `tools/tool_registry.py:97-103` | `TOOL_TIERS: Dict[str, str]` (public mutable) | Rename to `_TOOL_TIERS`; add `get_tool_tiers()` accessor; freeze the dict with `types.MappingProxyType` |
| `infrastructure/event_bus.py:14-18` | `_metrics = None` with `global _metrics` | Replace with `functools.cached_property` on the EventBus class or a module-level `_init_metrics()` that is idempotent |

**Verification:**
- `search_content "_rate_limit_buckets" --path tests` shows reset calls in fixtures
- `search_content "get_static"` returns zero matches (removed)
- `TOOL_TIERS` is no longer publicly mutable
- EventBus metrics init is test-resettable without `importlib.reload()`

**Risk:** LOW-MEDIUM — `get_static()` removal is the riskiest; need to trace all callers and ensure DI reaches them.

---

## Phase 3: Application Layer Hardening (Weeks 5-6)

### Goal: Fix MEDIUM-severity findings. Hardening the application layer against infrastructure leakage.

---

### Step 3.1 — Route file I/O through ConfigPort or FileStoragePort

**Target:** 8 application services using `open()` directly.

| Service | Current | Fix |
|---|---|---|
| `action_canonicalizer.py:62` | `open(path)` reads YAML | Inject `ConfigPort`; load via `config_port.load_yaml(path)` |
| `contract_loader.py:45` | `open(path)` reads YAML | Same as above |
| `harness_optimization_target.py:213` | `open(out_path, "w")` writes YAML | Inject `ConfigPort`; save via `config_port.save_yaml(path, data)` |
| `keyword_task_router.py:51` | `open(config_path)` reads YAML | Same as above |
| `model_aware_harness_resolver.py:79` | `open(fpath)` reads YAML | Same as above |
| `regression_suite.py:175` | `open(path)` reads JSONL | Inject `FileStoragePort` (new if needed, or use existing MemoryPort) |
| `self_improver.py:154,161` | `open(path)` reads YAML/JSON | Inject `ConfigPort` |
| `trajectory_exporter.py:70` | `open(...)` writes file | Inject `FileStoragePort` |

**Approach:**
1. Define `FileStoragePort` in `application/ports/` if it doesn't exist: `read_text(path) -> str`, `write_text(path, content)`, `read_yaml(path) -> dict`, `write_yaml(path, data)`
2. Create `LocalFileStorageAdapter` in `infrastructure/adapters/`
3. Wire through DI
4. Update each service to receive `FileStoragePort` or `ConfigPort` via constructor

**Verification:**
- `search_content "open\(" --path weebot/application/services` returns zero non-test, non-log matches
- All affected service tests pass with injected file storage mock

**Risk:** LOW — straightforward dependency injection refactor.

---

### Step 3.2 — Route env var access through ConfigPort

**Target:** 6 locations reading `os.environ` / `os.getenv` directly in application layer.

| Location | Current | Fix |
|---|---|---|
| `di/_factories.py:26,248` | `os.environ.get("WEEBOT_DB_BACKEND")`, `os.getenv("WEEBOT_HARNESS_VERSION")` | Already in DI layer — acceptable. Add comment that this is the canonical env→config boundary |
| `flows/states/plan_review.py:41` | `os.getenv("WEEBOT_PLAN_REVIEW_ENABLED")` | Read from `ConfigPort` (inject or access via `context.config`) |
| `flows/states/verifying.py:63,70` | `os.getenv("WEEBOT_COVE_ENABLED")`, `os.getenv("WEEBOT_COVE_QUESTIONS")` | Same as above |
| `services/cron_agent_runner.py:39` | `os.environ["WEEBOT_CRON_CONTEXT"]` | Read from `ConfigPort` |
| `services/model_registry/_service.py:29,42,58` | `os.getenv(...)` for API key detection | Read from `ConfigPort`; API key detection is a cross-cutting concern — move to `core/credential_sanitizer.py` or `config/settings.py` |

**Verification:**
- `search_content "os\.(environ|getenv)" --path weebot/application/flows` returns zero matches
- `search_content "os\.(environ|getenv)" --path weebot/application/services` returns zero matches (except DI layer)
- Feature flags and API key detection still work correctly

**Risk:** LOW — `ConfigPort` already exists; just need to use it consistently.

---

### Step 3.3 — Split god CQRS handlers file

**Target:** `weebot/application/cqrs/handlers.py` (779 lines, 7+ handler classes in one file)

**Action:** Split into one handler per file under `application/cqrs/handlers/`:

```
application/cqrs/handlers/
├── __init__.py              # Re-exports + register_default_handlers()
├── create_plan_handler.py
├── execute_step_handler.py
├── update_plan_handler.py
├── process_message_handler.py
├── ...                      # One file per handler
├── query_handlers.py        # Already separate — keep
└── conditions.py            # ProcessMessageCondition etc.
```

**Verification:**
- All CQRS tests pass
- `register_default_handlers()` still works
- Each handler file ≤ 150 lines

**Risk:** LOW — mechanical refactor. No behavior changes.

---

## Phase 4: Observability & Testability (Week 7)

### Goal: Close the remaining gaps to reach 9/10. No architecture changes — quality gates only.

---

### Step 4.1 — Add missing architecture fitness tests

**New tests to add to `tests/unit/test_architecture_fitness.py`:**

| Test | What It Checks |
|---|---|
| `test_application_does_not_import_infrastructure_persistence` | No `from weebot.infrastructure.persistence` in application/flows, /services, /cqrs, /agents (except DI) |
| `test_application_does_not_open_files` | No `open(` calls in application/services |
| `test_application_does_not_read_env` | No `os.environ` / `os.getenv` in application/flows, /services |
| `test_core_does_not_import_application_runtime` | Core imports of application/infrastructure are TYPE_CHECKING only |
| `test_port_has_multiple_implementations` | Every port in application/ports/ has ≥2 concrete adapter classes |
| `test_no_module_level_mutable_state` | No module-level `= {}`, `= []`, `= None` + `global` patterns outside of DI/config |

**Verification:**
- `pytest tests/unit/test_architecture_fitness.py -v` — all 25+ tests pass (up from 19)
- CI workflow `.github/workflows/architecture.yml` runs these on push

---

### Step 4.2 — Add cascade executor integration tests

**Target:** The newly extracted `CascadeExecutor` from Step 1.1.

**New tests:**
- `tests/unit/test_cascade_executor.py`: Unit tests with mocked LLMPort
  - Parallel probes dispatch correct models
  - First-completed cancels pending
  - Sequential fallback activates after parallel exhaustion
  - Live model rescue triggers on all-404
  - `AllModelsTrippedError` raised when everything fails
  - Fast-fail timeout reduction on auth errors
- `tests/integration/test_cascade_integration.py`: Integration tests with real LLMPort (gated behind `--integration` flag)

**Verification:**
- `pytest tests/unit/test_cascade_executor.py -v` — ≥12 tests, all pass
- Cascade coverage ≥ 85%

---

### Step 4.3 — Update architecture documentation

**Update `ARCHITECTURE.md`:**
1. Bump architecture score from 9.6/10 to reflect reality (temporarily 6/10, then 9/10 after remediation)
2. Update "Known Technical Debt" table — replace closed items with new items from this plan
3. Add new ADRs:
   - **ADR-006:** Port Rationalization — "Delete ports with <2 implementations"
   - **ADR-007:** ExecutorAgent Extraction — "Split god executor into cascade, tool, error, context collaborators"
4. Update layer map if port surface changes
5. Update enforcement section with new fitness tests

---

## Phase 5: Scaling Readiness (Ongoing — Trigger-Based)

*Not required to reach 9/10. Activated by scaling triggers from `ARCHITECTURE.md:186`.*

| Trigger | Action | When |
|---|---|---|
| >10 concurrent users | Make PostgreSQL the default state repository | Next scaling milestone |
| Multi-process deployment | Redis/RabbitMQ task queue; externalize PlanActFlow session state | Container orchestration |
| >100 tool definitions | Enforce `ToolRepositoryPort` for ALL tool access | Tool ecosystem growth |
| Cross-session agent communication | Activate `SwarmEventBusPort` over in-process bus | Multi-agent features |
| Compliance/audit requirements | Durable `EventStorePort` (PostgreSQL or Kafka) | Regulatory need |

---

## Score Projection After Remediation

| Dimension | Before | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Target |
|---|---|---|---|---|---|---|
| Layer Separation | 7 | 8 | 9 | 10 | 10 | **10** |
| Abstraction Discipline | 4 | 6 | 9 | 9 | 9 | **9** |
| Module Cohesion | 5 | 8 | 8 | 9 | 9 | **9** |
| Coupling Control | 6 | 7 | 8 | 9 | 9 | **9** |
| Async Hygiene | 9 | 9 | 9 | 9 | 9 | **9** |
| Failure Semantics | 9 | 9 | 9 | 9 | 10 | **10** |
| Testability | 6 | 7 | 8 | 8 | 9 | **9** |
| Scalability Readiness | 5 | 5 | 5 | 6 | 6 | **8** |
| **Overall** | **6.0** | **7.4** | **8.1** | **8.6** | **9.0** | **9.1** |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| ExecutorAgent extraction breaks cascade behavior | Medium | High | Extract one collaborator at a time; full test run between each |
| Port deletion breaks undiscovered dynamic import | Low | Medium | `search_content` before every deletion; CI catches import errors |
| Single-impl port consolidation causes widespread import churn | Medium | Medium | Batch by domain area; one commit per port group |
| `get_static()` removal breaks deep call-sites | Low | High | Trace all callers first; add DI parameter threading incrementally |
| Architecture score doesn't reach 9/10 due to scaling readiness | High | Low | Scaling readiness (8/10) is trigger-gated — acceptable to stay at 8; overall 9.0 still reachable |

---

## Progress Update (2026-06-18)

### Phase 1.2 ✅ (Complete)
**Goal:** Delete zero-implementation ports
**Result:** Deleted `capability_gate_port.py` and `truth_binding_port.py`. Both were explicitly marked `[DEPRECATED]` with zero callers and zero implementations.
**Correction:** The original audit claimed "20+ zero-impl ports" — this was inaccurate. Most listed ports have runtime callers and implementations in `application/services/` or `application/agents/`. Only 2 were truly deletable. Phase 2.1 target adjusted accordingly.

### Phase 1.3 ✅ (Complete)
**Goal:** Fix application→infrastructure leakage in 6 flows and CQRS handlers
**Result:**
- Created `application/ports/skill_store_port.py` (SkillStorePort) and `application/ports/trajectory_repository_port.py` (TrajectoryRepositoryPort)
- Made `SkillStore` and `TrajectoryRepository` implement the new ports
- Updated all 6 files: `skill_opt_flow.py`, `harness_opt_flow.py`, `failure_signature_handlers.py`, `skill_edit_handler.py`, `trajectory_handler.py`, `transfer_handler.py`
- **Critical fix:** `transfer_handler.py` no longer instantiates `SkillStore()` directly — now receives `SkillStorePort` via DI

### Phase 2.2 ✅ (Complete)
**Goal:** Fix core layer boundary violations
**Result:** Extracted `scan_for_injection()` function from `core/trust_boundary.py` into new `infrastructure/security/trust_boundary_scanner.py`. Removed the only runtime core→infrastructure import. Remaining two violations are TYPE_CHECKING-only or string literals (acceptable).

### Phase 2.3 ✅ (Complete)
**Goal:** Eliminate shared mutable state risks
**Result:**
- Added `reset_all_buckets()` to `utils/rate_limiter.py`
- Renamed `TOOL_TIERS` → `_TOOL_TIERS` in `tools/tool_registry.py`; added `get_tool_tier()`/`set_tool_tier()` accessors
- Added `_reset_metrics_cache()` to `infrastructure/event_bus.py`
- `Container.get_static()` in `application/di/__init__.py` deferred to Phase 1.1 (ExecutorAgent extraction) — its only caller is in `executor/_base.py`

### Phase 3 (Partial) ✅
**Goal:** Application layer hardening — reduce infrastructure imports
**Result:** Created `application/services/metrics_bridge.py` as the canonical application-layer entry point for Prometheus metrics. Updated 3 callers (`plan_act_flow.py`, `tool_collection.py`, `task_runner.py`) to import from the bridge instead of `weebot.infrastructure.observability.metrics`.

### Remaining Items
- **Phase 1.1:** Extract ExecutorAgent (1,414-line god class) — biggest remaining item
- **Phase 2.1:** Port consolidation — original 86% bloat metric was incorrect; most single-impl ports have callers. Needs re-baselining.
- **Phase 3 (rest):** Route file I/O through ports (8 services), route env var access (6 locations)
- **Phase 4:** Architecture fitness tests, cascade executor tests, docs update

## Definition of Done

- [ ] Phase 1.1: `ExecutorAgent` split into orchestrator + 4 collaborators, each ≤ 400 lines
- [ ] Zero-implementation ports deleted (21 files removed)
- [ ] Application→infrastructure leakage eliminated in flows and CQRS handlers
- [ ] Single-implementation ports consolidated (target: ≤15 ports remaining, all with ≥2 impls)
- [ ] Core layer boundary violations resolved
- [ ] Shared mutable state risks eliminated
- [ ] Application services use ConfigPort/FileStoragePort instead of direct `open()` and `os.getenv`
- [ ] CQRS handlers split into one file per handler
- [ ] Architecture fitness test suite: 25+ tests, 100% pass
- [ ] Cascade executor: 12+ unit tests, ≥85% coverage
- [ ] `ARCHITECTURE.md` updated with current score, new ADRs, and updated debt table
- [ ] CI workflow passes on `main`
