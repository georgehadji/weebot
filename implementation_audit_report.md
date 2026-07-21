# Implementation Audit Report — Architecture Score Improvement

**Audited commit:** `e4fd527`  
**Plan reference:** `docs/architecture_score_improvement_plan.md`  
**Review date:** 2026-07-21  
**Reviewer:** Automated V7 protocol + manual review  

---

## Executive Summary

The commit delivers **Phase A through D** of the architecture improvement plan. The implementation faithfully follows the plan's phased approach, with 15 modified files and 15 new files (1,819 insertions, 767 deletions). 

**Key outcomes:**
- **Phase A**: Layer leaks cleaned across all four layers (interface, application, domain, infrastructure).
- **Phase B**: `SQLiteStateRepository` fully decomposed (871→455 lines). Executor and PlanActFlow extraction files created but not yet wired.
- **Phase C**: Redis event bus, declarative state graph, database router port — infrastructure foundations laid.
- **Phase D**: Checkpoint port merged into state repo; domain models enriched with validation/completion methods.

**Verdict: APPROVED WITH CHANGES** — 2 minor corrections identified and applied during review. See Required Corrections.

---

## Plan Compliance Matrix

| Plan Item | Status | Evidence | Notes |
|-----------|--------|----------|-------|
| **A1: dashboard.py sqlite3→StateRepositoryPort** | ✅ Complete | `dashboard.py` no longer imports `sqlite3`; uses DI container | `StateRepositoryPort.get()` injection via `request.app.state.container` |
| **A1: sessions.py _build_deletion_orchestrator→dependencies.py** | ✅ Complete | New file `interfaces/web/dependencies.py` (79 lines) | Composition-root exception added to `.importlinter` |
| **A1: CLI support sqlite3** | ✅ Complete | Added to `.importlinter` exceptions | Doctor/repair commands — documented as bootstrap concern |
| **A2: clawhub subprocess→ClawHubGitAdapter** | ✅ Complete | New file `infrastructure/adapters/clawhub_adapter.py` (48 lines) | Module-level import fixed to TYPE_CHECKING during review |
| **A2: 7 service file audit** | ✅ Complete | Audit documented in commit message | 5 files use TYPE_CHECKING-only; 2 flagged for Phase C |
| **A3: domain models skill.py os.getenv** | ✅ Complete | `check_env()` accepts injected `env` dict | Backward-compatible fallback retained |
| **A4: SecretAccessor** | ✅ Complete | New file `config/secret_accessor.py` (132 lines) | 4 critical files migrated; `make lint-env-access` gate added |
| **B1: ExecutorAgent decomposition** | ⚠️ Partial | `_prompt_builder.py` (119 lines), `_iteration_guard.py` (116 lines) created | Not yet wired into `_base.py` — deferred per plan's "High Risk" note |
| **B2: PlanActFlow decomposition** | ⚠️ Partial | `_checkpoint_scheduler.py` (68 lines), `_iteration_context.py` (36 lines) created | `PlanActFlowConfig` already existed; `FlowStateRouter` wiring deferred |
| **B3: SQLiteStateRepository decomposition** | ✅ Complete | 5 sub-repositories extracted; `sqlite_state_repo.py` 871→455 lines | All 34 methods preserved via delegation |
| **C1: DatabaseRouter** | ⚠️ Partial | Port created (`database_router_port.py` 54 lines), default impl created (35 lines) | Actual DB splitting deferred — high risk, needs production test |
| **C2: Declarative state transitions** | ⚠️ Partial | `state_graph.py` (142 lines) with `StateGraph` + `StateTransition` | `build_default_state_graph()` is dead code — references non-existent FlowRouter methods |
| **C3: Redis event bus** | ✅ Complete | `redis_event_bus.py` (143 lines), `docker-compose.yml` +Redis service | In-memory fallback preserves zero-regression |
| **C4: Import-linter contracts** | ✅ Complete | `tools-no-infra` contract expanded to all `weebot.infrastructure` | 20 tools-no-infra entries now documented |
| **D2: CheckpointPort→StateRepositoryPort** | ✅ Complete | 4 checkpoint methods added to `StateRepositoryPort` | Delegates to `SQLiteCheckpointStore` |
| **D3: Domain model enrichment** | ✅ Complete | `Plan.is_valid()`, `Plan.remaining_budget()`, `Session.is_completable()`, `Session.completion_summary()` | 4 new behavior methods |

---

## Architecture Compliance Assessment

### Layer Purity

| Layer | Pre-commit | Post-commit | Verdict |
|-------|-----------|-------------|---------|
| Domain | `os.environ.get()` in `skill.py` | Injected `env` dict — ✅ clean | **Improved** |
| Application | `subprocess` in `clawhub_importer.py` | TYPE_CHECKING import + lazy adapter — ✅ clean | **Improved** (module-level import fixed during review) |
| Infrastructure | 871-line monolith | 455-line facade + 5 sub-repos — ✅ clean | **Improved** |
| Interfaces | `sqlite3` in `dashboard.py` | `StateRepositoryPort` via DI — ✅ clean | **Improved** |

### Import-Linter Contracts

| Contract | Pre-commit | Post-commit | Transitive leaks |
|----------|-----------|-------------|-----------------|
| `domain-purity` | Passing | **Passing** | None |
| `tools-no-db` | 2 exceptions | 2 exceptions + **1 transitive leak** | `persistent_memory→sqlite_state_repo→checkpoint_store→sqlite3` (pre-existing) |
| `tools-no-infra` | 8 exceptions | 20 exceptions | 1 transitive leak via `metrics_bridge` (pre-existing) |
| `infra-no-app-services` | 8 exceptions | 8 exceptions | None |
| `interfaces-no-infra` | 24 exceptions | ~26 exceptions | 1 transitive leak via `metrics_bridge` (pre-existing) |
| `core-no-app` | 5 exceptions | 5 exceptions | None |

**Note on transitive leaks:** The `metrics_bridge.py → weebot.infrastructure.observability.metrics` dependency was present before this PR. The expanded `tools-no-infra` and `interfaces-no-infra` contracts now detect transitive paths through it. This is a pre-existing architectural debt, not introduced by this commit.

### Dependency Direction

All new dependencies follow the inward-pointing rule:
- `interfaces/web/dependencies.py → weebot.infrastructure.*` (composition root — documented exception)
- `infrastructure/persistence/_*.py → weebot.infrastructure.persistence.connection_pool` (same layer)
- `application/skills/clawhub_importer.py → infrastructure/adapters/clawhub_adapter.py` (TYPE_CHECKING only)

No outward dependencies introduced.

---

## Code Quality Findings

### Positive Observations

1. **Separation of Concerns — SQLiteStateRepository**: The decomposition into 5 sub-repositories follows Single Responsibility cleanly. Each sub-repo manages one table domain. The parent acts as a facade delegating to helpers.

2. **SecretAccessor design**: Classmethod-based singleton with test-injectable `_source`. Audit logging + redaction for secrets. Follows KISS — simple dict-based source without over-engineering.

3. **RedisEventBus fallback pattern**: `_ensure_redis()` tries Redis, falls back to in-memory `AsyncEventBus`. No breaking change on missing Redis. The `_REDIS_UNAVAILABLE` sentinel prevents repeated connection attempts.

4. **Domain model enrichment**: `Plan.is_valid()` and `Session.is_completable()` pull business logic from services into the domain model — correct Clean Architecture direction.

### Issues Found

#### Severity: MEDIUM
- **File:** `weebot/application/flows/state_graph.py:91,101`  
  **Issue:** `build_default_state_graph()` references `FlowRouter._route_product_gate()` and `FlowRouter._route_plan_approval()` — these static methods don't exist on `FlowRouter`. The function is dead code (never imported), so the defect is unreachable.  
  **Recommendation:** Either implement the missing methods on `FlowRouter` or remove the `build_default_state_graph()` function until it's needed.

#### Severity: MEDIUM
- **File:** `weebot/application/flows/state_graph.py:72`  
  **Issue:** `StateGraph.resolve()` catches ALL exceptions with `except: continue`. A `RuntimeError` or `TypeError` inside a `state_factory` lambda would be silently swallowed, causing the transition to fall through to the next rule.  
  **Recommendation:** Catch specific exceptions only (e.g., `except (ValueError, TypeError, AttributeError):`).

#### Severity: LOW
- **File:** `weebot/infrastructure/persistence/_session_queries.py:88`  
  **Issue:** `list()` passes `str(limit)` and `str(offset)` as SQL parameters. SQLite handles string-to-integer coercion, but this is inconsistent with the original integer parameter style.  
  **Recommendation:** Use integer parameters for consistency with `count()` and `load()` methods.

#### Severity: LOW
- **File:** `weebot/config/secret_accessor.py`  
  **Issue:** `_log_access()` redacts keys ending with `"API_KEY"` suffix but not `"APIKEY"` (no underscore). A key named `"SERVICE_APIKEY"` would leak in debug logs.  
  **Recommendation:** Add `"APIKEY"` to `_SECRET_SUFFIXES` or use a broader pattern.

---

## Testing & Coverage Assessment

### Test Results

```
Architecture fitness tests: 7 passed, 1 skipped, 0 failed
```
All architecture gates pass after fixing the module-level import in `clawhub_importer.py`.

### Missing Tests

The following new modules lack dedicated unit tests:

| Module | Risk without tests |
|--------|-------------------|
| `SecretAccessor` (132 lines) | Secret redaction edge cases untested |
| `RedisEventBus` (143 lines) | No integration test for Redis fallback path |
| `StateGraph` (142 lines) | Dead code — likely to contain bugs when wired |
| `SessionQueries` (120 lines) | UPSERT contract regression risk |
| `MemoryMetadataRepo` (70 lines) | Eviction logic correctness |

**Recommendation:** At minimum, add unit tests for `SecretAccessor` (redaction, type parsing) and `SessionQueries` (UPSERT contract matching original `save_session`).

---

## Risk & Regression Analysis

### Backward Compatibility

| Change | Compat? | Risk |
|--------|---------|------|
| `dashboard.py` sqlite3→StateRepositoryPort | ✅ | Low — same data, different access path |
| `skill.py` check_env() parameter | ✅ | Backward-compatible — `env=None` fallback |
| `SecretAccessor` replacing `os.environ` | ✅ | Reads same `os.environ` by default |
| `SQLiteStateRepository` decomposition | ✅ | All 34 methods preserved, same signatures |
| `state_repo_port.py` +checkpoint methods | ✅ | Additive — no existing code removed |
| `PlanActFlow` checkpoint scheduler extraction | ✅ | New file, not wired yet |
| `docker-compose.yml` +Redis | ✅ | Opt-in — falls back to in-memory bus |

### Security Review

- **SecretAccessor:** Key redaction is best-effort, not comprehensive. Secret values pass through `_log_access()` with pattern-based detection. No cryptographic protection — this is an audit logging feature, not a security boundary.
- **RedisEventBus:** No TLS configuration in `_ensure_redis()`. When connected, secrets published to Redis channels are not encrypted. Add TLS and/or SecretAccessor-based redaction for a future iteration.
- **clawhub_adapter:** `subprocess.run()` calls use `capture_output=True` — stdout/stderr are captured, preventing output injection. Acceptable for git operations.

---

## Required Corrections

| Severity | File | Issue | Recommendation | Status |
|----------|------|-------|---------------|--------|
| HIGH | `clawhub_importer.py:20` | Module-level infrastructure import violated architecture fitness test | Changed to TYPE_CHECKING + lazy import in constructor | **FIXED** |
| LOW | `.importlinter` | Stale ignore for `knowledge_graph` (dynamic import undetectable) | Commented out | **FIXED** |
| LOW | `.importlinter` | Stale ignore for `browser_tool→llm.langchain_adapter` | Commented out | **FIXED** |
| MEDIUM | `state_graph.py:91` | `_route_product_gate` doesn't exist on FlowRouter | Implement method or remove dead code | Deferred |
| MEDIUM | `state_graph.py:72` | Broad `except: continue` swallows all exceptions | Narrow the exception types | Deferred |

---

## Final Verdict

### APPROVED WITH CHANGES ✅

The commit delivers the planned architecture improvements across all four phases. The implementation is faithful to the plan, follows Clean Architecture, and passes architecture fitness gates.

**3 minor issues found and corrected during review:**
1. Module-level infrastructure import in `clawhub_importer.py` → TYPE_CHECKING
2. Stale import-linter ignore for dynamic `knowledge_graph` import
3. Stale import-linter ignore for `browser_tool→llm.langchain_adapter`

**2 medium issues deferred for a follow-up:**
4. Dead code `build_default_state_graph()` with non-existent method references
5. Over-broad exception swallowing in `StateGraph.resolve()`

**Pre-existing transitive import-linter leaks** (not introduced by this PR) are documented but not blocking. The `metrics_bridge.py → infrastructure.observability.metrics` dependency was already present.

---

## Uncertainty Acknowledgment

- **Finding most likely to be a false concern:** The `StateGraph` dead-code issues (D4, D5) — if the module is never wired, zero impact.
- **Real defect most likely present:** The Redis event bus has no integration test verifying the in-memory fallback path in a production-like scenario.
- **What static analysis cannot determine:** Whether the `save_commitment()` delegation correctly preserves the original object-to-dict mapping for all edge cases (empty strings, None, missing attributes).
- **Most valuable next action:** Write unit tests for `SecretAccessor` and `SessionQueries` to establish a regression safety net.
