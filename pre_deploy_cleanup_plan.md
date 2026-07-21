# Pre-Deploy Cleanup & Ruff Remediation Plan

**Baseline:** Implementation audit `implementation_audit_report.md` (2026-07-21)
**Scope:** Fix all remaining ruff issues + resolve all deploy-blocking items from Phase 1 audit
**Target:** Clean ruff run (0 errors) on Phase 1 files + all audit corrections applied

---

## 1. CURRENT STATE

### 1.1 Ruff Issues — 82 errors across 6 files

| File | Count | Auto-fixable | Manual | Severity Distribution |
|------|-------|-------------|--------|-----------------------|
| `health.py` | 31 | 18 | 2 E501 + 1 E402 + 2 B008 (suppress) | Mostly W293 whitespace |
| `sessions.py` | 22 | 17 | 8 B008 (FastAPI pattern, suppress) | +1 W291 trailing |
| `responses.py` | 16 | 16 | 0 | UP006/UP045/UP035/F401 only |
| `auth.py` | 1 | 1 | 0 | UP045 Optional[str] |
| `ops_router.py` | 2 | 2 | 0 | W293 whitespace |
| `orchestrator.py` | 0 | — | — | ✅ Already clean |

### 1.2 Deploy-Blocking Items (from audit report)

| # | Item | Status | Section |
|---|------|--------|---------|
| DB-1 | Wire `gateway_session_store` into orchestrator | ❌ Missing | §2.2 |
| DB-2 | Wire `sqlite_knowledge_graph` into orchestrator | ❌ Missing | §2.2 |
| DB-3 | Add ownership check to `chat_router.py` | ❌ Missing | §2.3 |
| DB-4 | Frontend WS auth manual E2E test | ❌ Not done | §2.4 |

### 1.3 Recommended Corrections (from audit report)

| # | Item | Severity |
|---|------|----------|
| RC-1 | Add `from None` to B904 violations | ✅ DONE (during audit) |
| RC-2 | Fix infrastructure import in ops_router | ✅ DONE (during audit) |
| RC-3 | Unused imports/vars in orchestrator + sessions | ✅ DONE (during audit) |
| RC-4 | Gateway + knowledge graph store wiring | P2 — covered by DB-1/DB-2 |
| RC-5 | `chat_router.py` ownership check | P2 — covered by DB-3 |

---

## 2. FIX PLAN — RUFF ISSUES

### 2.1 Auto-fixable Pass (61 errors, ~30 seconds)

All W293 (blank-line whitespace), W291 (trailing whitespace), UP006 (Dict→dict, List→list), UP045 (Optional→X|None), UP035 (deprecated typing), and F401 (unused imports) are auto-fixable with `ruff check --fix`.

**Command:**
```bash
ruff check --fix \
  weebot/interfaces/web/auth.py \
  weebot/interfaces/web/routers/health.py \
  weebot/interfaces/web/routers/ops_router.py \
  weebot/interfaces/web/routers/sessions.py \
  weebot/interfaces/web/schemas/responses.py
```

**Architecture note:** These are purely cosmetic/syntax modernizations. No Clean Architecture boundaries are affected. The `pyproject.toml` already targets `py310`, and `from __future__ import annotations` is present in all files, so `X | None` and `dict`/`list` are safe.

**Risk:** Very low. Ruff's `--fix` is safe for all these rules. Verify with `ruff check` after.

### 2.2 E501 — Line Too Long (2 errors in health.py)

| Line | Current | Fix |
|------|---------|-----|
| 48 | `message=f"{len(available)} providers available" if available else "No providers configured",` (104 chars) | Extract message variable before the `HealthComponent` constructor |
| 62 | `pool_msg = f"Database operational ({len(sessions)} sessions found)" if sessions else "Database operational (no sessions)"` (129 chars) | Split: `count = len(sessions); pool_msg = f"Database operational ({count} sessions)" if count else "Database operational (no sessions)"` |

**Architecture note:** Pure refactoring within the router function. No boundary change.

### 2.3 E402 — Module-Level Import Not at Top (1 error in health.py)

Line 19: `from weebot.interfaces.web.schemas import HealthResponse, HealthComponent`

This import is after the `get_state_repo` function definition (which needs `Request` from FastAPI but not the schemas). The fix: move the import to the top of the file (after the existing FastAPI imports at line 8), and move the `get_state_repo` function below it. Since `get_state_repo` doesn't use the schemas, this is safe.

**Architecture note:** Interfaces layer. Both imports stay within `weebot/interfaces/web/`. No boundary violation.

### 2.4 B008 — Depends in Defaults (8 errors in health.py + sessions.py)

These are FastAPI's standard dependency injection pattern: `state_repo: StateRepositoryPort = Depends(get_state_repo)`. The B008 rule warns about mutable defaults, but `Depends()` returns a callable wrapper, not a mutable default.

**Decision: Suppress, don't change.**  
- Changing to the alternative (module-level singleton) would break the per-request identity-resolving pattern.
- This is a project-wide pattern used in every FastAPI router.
- **Recommended:** Add `B008` to `tool.ruff.lint.ignore` in `pyproject.toml` under the existing ignore list.

Alternatively, add per-line `# noqa: B008` comments on each of the 8 lines. The `pyproject.toml` approach is cleaner.

**Architecture note:** No change needed. This is a pattern recognized as safe in the FastAPI ecosystem.

---

## 3. FIX PLAN — DEPLOY-BLOCKING ITEMS

### 3.1 DB-1 + DB-2: Wire Missing Stores into Orchestrator

**Files:** `weebot/interfaces/web/routers/sessions.py` (lines ~50–82, `_build_deletion_orchestrator`)

**What to add:**
```python
# Gateway session store
try:
    from weebot.infrastructure.persistence.gateway_session_store import (
        SQLiteGatewaySessionStore,
    )
    gateway_store = container.get(SQLiteGatewaySessionStore)
    if hasattr(gateway_store, "delete"):
        orch.add_store("gateway_session_store", gateway_store, "delete")
except (KeyError, Exception):
    pass

# Knowledge graph
try:
    from weebot.infrastructure.persistence.sqlite_knowledge_graph import (
        SQLiteKnowledgeGraph,
    )
    kg = container.get(SQLiteKnowledgeGraph)
    orch.add_store("knowledge_graph", kg, "delete_session_data")
except (KeyError, Exception):
    pass
```

**Architecture note:** The `_build_deletion_orchestrator` function already imports infrastructure adapters via try/except (as noted in the audit for `SQLiteCheckpointStore`). This follows the existing pattern for Phase 1. In Phase 3, extract all store registration to a DI-composed factory in `weebot/interfaces/web/dependencies.py`.

**To verify:** grep for the actual method names on each store (`.delete()`, `.delete_session()`, `.delete_session_data()`) before writing the registration code.

**Risk:** The knowledge graph store may not have a simple `session_id`-scoped delete method. If not, skip it with a comment explaining the limitation.

### 3.2 DB-3: Ownership Check in chat_router.py

**Files:** `weebot/interfaces/web/routers/chat_router.py`

The chat_router has these session-accessing endpoints:
- `POST /api/chat` — creates or loads a session, then runs it
- `GET /api/chat/history` — lists sessions
- `GET /api/chat/{id}` — gets session details

**Plan:**

1. Add import:
   ```python
   from weebot.interfaces.web.auth import get_current_user_id, verify_session_ownership
   ```

2. `GET /api/chat/{id}`: After loading the session, add:
   ```python
   await verify_session_ownership(http_request, session.user_id)
   ```

3. `GET /api/chat/history`: Override the user_id filter with `get_current_user_id(http_request)`, same pattern as `sessions.py:list_sessions`.

4. `POST /api/chat`: Two cases:
   - **New session**: Override `user_id` with `get_current_user_id(http_request)` (same as `sessions.py:create_session`).
   - **Existing session**: Load, verify ownership, continue.

**Architecture note:** Same pattern as already implemented in `sessions.py` and `ops_router.py`. `get_current_user_id` derives a stable ID from the API key via SHA-256. `verify_session_ownership` returns 404 on mismatch (no information leakage). Feature-flag `WEEBOT_ENFORCE_SESSION_OWNERSHIP` covers both routers.

### 3.3 DB-4: Frontend WS Auth E2E Verification

This is a manual test, not a code change. Steps:

1. Start backend with `WEEBOT_API_KEY=test-key`:
   ```bash
   WEEBOT_API_KEY=test-key python -m weebot.interfaces.web.main
   ```

2. Start frontend:
   ```bash
   cd weebot-ui && npm run dev
   ```

3. Open browser → `http://localhost:3000`

4. Enter `test-key` in the ConnectionStatus API key field.

5. Verify:
   - Health check succeeds (no ws_token in response)
   - WebSocket connects with token in query param
   - Session creation works
   - Session operations work (list, get, run, cancel, delete)
   - No 401 or 403 errors for own sessions

6. Test ownership:
   - Create session with `test-key`
   - Switch to different API key (or clear sessionStorage)
   - Verify 404 when accessing the previous session

---

## 4. EXECUTION ORDER

| Step | Action | Time | Depends On |
|------|--------|------|------------|
| 1 | Run `ruff check --fix` on all 6 files | 1 min | — |
| 2 | Fix E501 long lines (2 manual reflows in health.py) | 5 min | — |
| 3 | Fix E402 import order (move import to top of health.py) | 2 min | — |
| 4 | Add `B008` to `pyproject.toml` ignore list | 1 min | — |
| 5 | Run `ruff check` to confirm 0 errors | 1 min | 1–4 |
| 6 | Verify store method names via grep (prep for DB-1/DB-2) | 5 min | — |
| 7 | Wire gateway_session_store into orchestrator | 5 min | 6 |
| 8 | Wire knowledge_graph into orchestrator (or skip with comment) | 5 min | 6 |
| 9 | Add ownership check to chat_router.py (all 3 endpoints) | 10 min | — |
| 10 | Run `ruff check` on chat_router.py | 1 min | 9 |
| 11 | Run `pytest tests/ -v --tb=short` to verify no regressions | 5 min | 1–10 |
| 12 | Manual E2E frontend WS auth test (DB-4) | 10 min | 1–11 |
| **Total** | | **~50 min** | |

---

## 5. ARCHITECTURE COMPLIANCE CHECKLIST

| Rule | How Each Step Respects It |
|------|--------------------------|
| **Domain purity** | No domain layer files touched |
| **Interfaces-no-infra** | `_build_deletion_orchestrator` already uses try/except importlib pattern for store registration. `chat_router.py` only imports from `interfaces/web/auth.py` (same layer). |
| **Tools-no-db** | No tool layer files touched |
| **Infra-no-app-services** | No infrastructure files touched (store registration happens in interfaces layer) |
| **Feature flag pattern** | `WEEBOT_ENFORCE_SESSION_OWNERSHIP` already covers all routers; chat_router will use same flag |
| **Error handling** | Same `logger.exception()` + generic client message pattern as already applied in Phase 1 |

---

## 6. VERIFICATION AFTER FIXES

```bash
# 1. Ruff — zero errors on Phase 1 files
ruff check \
  weebot/interfaces/web/auth.py \
  weebot/application/services/session_deletion_orchestrator.py \
  weebot/interfaces/web/routers/health.py \
  weebot/interfaces/web/routers/ops_router.py \
  weebot/interfaces/web/routers/sessions.py \
  weebot/interfaces/web/routers/chat_router.py \
  weebot/interfaces/web/schemas/responses.py

# 2. All Python files parse
python -c "
import ast, sys
files = ['weebot/interfaces/web/auth.py', ...]
for f in files:
    ast.parse(open(f).read())
print('All OK')
"

# 3. Import-linter (if make available)
make lint-imports 2>/dev/null || echo "make not available — skip"

# 4. Test suite
pytest tests/ -v --tb=short

# 5. Secret scan still works
bash scripts/check-secrets.sh --ci
```

---

*Plan version: 1.0 · All steps respect project Clean Architecture boundaries · Total estimated effort: ~50 minutes*
