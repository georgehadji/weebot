# Technical Debt Inventory

**Codebase:** Weebot AI Agent Framework  
**Assessment Date:** 2025-07-21

---

## Debt Classification

| Category | Count | Estimated Effort |
|----------|-------|-----------------|
| 🔴 Critical (blocks features, causes bugs) | 3 | 2-4 hours |
| 🟠 High (degrades quality, scales poorly) | 6 | 8-16 hours |
| 🟡 Medium (maintainability concern) | 8 | 16-24 hours |
| 🔵 Low (cosmetic, minor friction) | 10+ | 24+ hours |

---

## 🔴 Critical Debt

### DEBT-001: Indentation Bug as Architectural Symptom

**File:** `weebot/infrastructure/adapters/llm/resilient_adapter.py`  
**Root Issue:** The `_sanitize_error` function contains two stray lines (`LLMCache = None`, `CacheKey = None`) that corrupt module-level state. This bug exists because:
1. No type checker flags it (assigning `None` to a variable is valid Python)
2. No test exercises the cache after error sanitization
3. The code was likely copy-pasted from the import block above

**Debt Cost:** Silent performance degradation in production; debugging time when cache misses are investigated.

**Resolution:** Remove the two lines + add regression test.

---

### DEBT-002: `hmac.new` Typo as Testing Gap Symptom

**File:** `weebot/tools/bash_tool.py`  
**Root Issue:** `hmac.new()` should be `hmac.HMAC()`. The fact that this shipped indicates:
1. The security override path has ZERO test coverage
2. No integration test exercises the admin override flow
3. The code was likely written in one pass and never executed

**Debt Cost:** Dead code that gives false confidence about admin override capability.

**Resolution:** Fix typo + add test + decide if the feature is actually needed.

---

### DEBT-003: Dual Event Storage Systems

**Files:** `weebot/infrastructure/event_store.py` + `sqlite_state_repo.py`  
**Root Issue:** Events are stored in two incompatible systems:
1. `EventStore` (sync sqlite3 in `~/.weebot/events.db`) — used for cost tracking
2. `SQLiteStateRepository` (async aiosqlite in `./weebot_sessions.db`) — used for session state

**Debt Cost:**
- Developers confused about which store to query
- Cost data not joinable with session state data
- FTS5 search only covers one store
- Two different persistence patterns to maintain

**Resolution:** Migrate EventStore to use the same connection pool as SQLiteStateRepository, or merge into a single database with proper table separation.

---

## 🟠 High Debt

### DEBT-004: PlanActFlow Constructor Explosion

**File:** `weebot/application/flows/plan_act_flow.py`  
**Metric:** 30+ constructor parameters, 350+ lines in `__init__`  
**Debt Cost:** Every new feature adds another parameter. Testing requires mocking all deps.  
**Resolution:** Extract into config object (partially done with `PlanActFlowConfig`) + extract collaborators.

---

### DEBT-005: Container Self-Instantiation Anti-Pattern

**Files:** Multiple (bash_tool.py, plan_act_flow.py, python_tool.py)  
**Pattern:**
```python
if sandbox is None:
    from weebot.application.di import Container
    container = Container()
    container.configure_defaults()
    sandbox = container.get(SandboxPort)
```
**Debt Cost:** 
- Multiple Container instances with separate singleton caches
- Violates dependency inversion (components create their own dependencies)
- Makes testing harder (global state from Container)

**Resolution:** Remove all self-instantiation. If a tool is created without DI, raise an error or use a module-level sentinel.

---

### DEBT-006: `_DEFAULT_RULES` Hardcoded in approval_policy.py

**File:** `weebot/core/approval_policy.py`  
**Issue:** Command approval rules are hardcoded Python lists. Adding/removing rules requires code changes and redeployment.  
**Debt Cost:** Cannot be configured per-deployment without code changes.  
**Resolution:** Load rules from YAML config (similar to `behavioral_rules.yaml`).

---

### DEBT-007: Mixed Sync/Async Database Access Patterns

**Files:** `event_store.py` (sync), `sqlite_state_repo.py` (async), `scheduler.py` (sync)  
**Issue:** Three different patterns for SQLite access:
1. Sync `sqlite3` with `asyncio.to_thread` wrapper
2. Async `aiosqlite` with connection pool
3. Raw sync `sqlite3` without async wrapper

**Debt Cost:** Cognitive overhead, potential thread pool exhaustion, no shared connection management.  
**Resolution:** Standardize on async aiosqlite with the existing connection pool for all SQLite access.

---

### DEBT-008: No Structured Error Types for Tool Failures

**File:** `weebot/tools/base.py`  
**Issue:** `ToolResult` uses string `error` field. No structured error codes allow programmatic handling.  
**Debt Cost:** The Plan-Act flow cannot distinguish between "tool timed out" (retry) vs "tool denied by policy" (don't retry) without string matching.  
**Resolution:** Add `error_code: Optional[str]` field to ToolResult (partially exists in web layer but not tools).

---

### DEBT-009: WebSocket Test UI Embedded as String Literal

**File:** `weebot/interfaces/web/main.py`  
**Issue:** 80+ lines of HTML/CSS/JS are stored as a Python string constant (`WEBSOCKET_TEST_HTML`).  
**Debt Cost:** No syntax highlighting, no IDE support, must escape special chars, pollutes the module.  
**Resolution:** Move to a static HTML file served by `StaticFiles`.

---

## 🟡 Medium Debt

### DEBT-010: Inconsistent Logging

**Pattern:** Mix of `logger.info()`, `self._log.info()`, `logging.getLogger(__name__)`, and `_log.info()` across the codebase.  
**Resolution:** Standardize on StructuredLogger for application layer, stdlib for infrastructure.

---

### DEBT-011: Missing Type Annotations in DI Container

**File:** `weebot/application/di/__init__.py`  
**Issue:** `register()` accepts `type` but many registrations use string keys (e.g., `"session_persistence"`, `"activity_stream"`).  
**Debt Cost:** No IDE autocompletion, no static type checking for string-keyed bindings.  
**Resolution:** Create typed protocol/enum for all DI keys.

---

### DEBT-012: No Migration System for Schema Changes

**Issue:** `sqlite_state_repo.py` uses `CREATE TABLE IF NOT EXISTS` for schema. If columns are added/renamed, existing databases won't be migrated.  
**Debt Cost:** Manual database deletion required for schema changes.  
**Resolution:** Use Alembic (already in requirements.txt) or simple version-check migrations.

---

### DEBT-013: Redundant Security Layers Without Clear Ownership

**Pattern:** Commands pass through:
1. `CommandSecurityAnalyzer` (multi-layer)
2. `BashGuard` (pattern matching)
3. `ExecApprovalPolicy` (rule-based)

All three check overlapping patterns. No clear documentation of which layer catches what.  
**Resolution:** Define clear responsibilities: Analyzer = attack detection, BashGuard = system protection, Policy = user confirmation.

---

### DEBT-014: `asyncio` Import Missing in Scheduler

**File:** `weebot/scheduling/scheduler.py`  
**Issue:** `asyncio.iscoroutinefunction(func)` is used but `asyncio` is never imported at module level. It works because APScheduler imports it, but this is fragile.  
**Resolution:** Add `import asyncio` at top of file.

---

### DEBT-015: Configuration Scattered Across Multiple Sources

**Issue:** Configuration lives in:
- `.env` file (WeebotSettings)
- `config/settings.py` (module constants)
- `config/constants.py` (more constants)
- `config/model_refs.py` (model strings)
- `config/tool_config.py` (tool settings)
- `config/feature_flags.py` (feature toggles)
- `config/jobs.yaml` (scheduler config)
- `config/behavioral_rules.yaml` (rules)

**Debt Cost:** Difficult to know where a setting lives. Some settings duplicated.  
**Resolution:** Centralize into WeebotSettings with clear section comments, or create a config registry.

---

### DEBT-016: Dead Code Paths

**Examples:**
- `weebot/state_coordinator.py` and `weebot/state_manager.py` appear to be legacy files
- `weebot/nlp_understanding.py` at module root (duplicates `application/services/nlp_understanding.py`)
- `weebot/notifications.py` at module root (duplicates infrastructure notifications)
- `weebot/ai_router.py` at module root (duplicates infrastructure routing)

**Resolution:** Verify no imports reference these files, then delete.

---

### DEBT-017: Test Artifacts Not Cleaned Up

**Evidence:** `.test-work/` directory contains 30+ test database files that persist between runs.  
**Resolution:** Use `tmp_path` fixture consistently; add `conftest.py` cleanup; add `.test-work/` to `.gitignore`.

---

## Technical Debt Prioritization Matrix

| ID | Category | Effort | Risk if Unfixed | Priority |
|----|----------|--------|-----------------|----------|
| DEBT-001 | Bug | 15 min | High (silent degradation) | P0 |
| DEBT-002 | Bug | 30 min | Low (fails closed) | P1 |
| DEBT-003 | Architecture | 4 hours | Medium (confusion, dual sources) | P2 |
| DEBT-004 | Complexity | 8 hours | Medium (velocity drag) | P2 |
| DEBT-005 | Architecture | 2 hours | Medium (resource leaks) | P1 |
| DEBT-006 | Configurability | 2 hours | Low | P3 |
| DEBT-007 | Consistency | 4 hours | Medium (thread pool) | P2 |
| DEBT-008 | Design | 2 hours | Medium (retry logic) | P2 |
| DEBT-009 | Hygiene | 30 min | Negligible | P3 |
| DEBT-010 | Consistency | 2 hours | Low | P3 |
| DEBT-011 | Type Safety | 2 hours | Low | P3 |
| DEBT-012 | Operations | 3 hours | High (data loss on upgrade) | P1 |
| DEBT-013 | Clarity | 2 hours | Low | P3 |
| DEBT-014 | Correctness | 5 min | Low (works by accident) | P3 |
| DEBT-015 | Clarity | 4 hours | Low | P3 |
| DEBT-016 | Dead Code | 1 hour | Negligible | P3 |
| DEBT-017 | Testing | 30 min | Low | P3 |
