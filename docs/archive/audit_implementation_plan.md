# Implementation Plan for DeepSeek V4 Flash

**Codebase:** Weebot AI Agent Framework  
**Generated:** 2025-07-21  
**Scope:** Remaining remediation tasks after Phase 1-3 completion

---

## Executive Summary

Phase 1-3 (Critical/High priority) are **COMPLETE** — 10 code fixes applied, 90 new tests passing, 2 commits pushed.

This plan covers the **remaining work**: Phase 4 strategic improvements that require architectural refactoring.

---

## Completed Work (Do Not Re-do)

| Task | Files | Commit |
|------|-------|--------|
| Fix CORS wildcard | `web/main.py` | `4b4c96f` |
| Add WebSocket auth | `web/main.py` | `4b4c96f` |
| Fix HMAC override | `bash_tool.py` | `4b4c96f` |
| Fix cache corruption | `resilient_adapter.py` | `4b4c96f` |
| Add SQL pagination | `sessions.py` | `4b4c96f` |
| Replace self-instantiated Containers | `bash_tool.py`, `python_tool.py` | `4b4c96f` |
| Add load_events parameter | `sqlite_state_repo.py` | `4b4c96f` |
| Fix FTS5 write amplification | `sqlite_state_repo.py` | `4b4c96f` |
| Fix HTML injection regex | `security_validators.py` | `b9a2ab3` |
| Add timing-safe comparison | `web/main.py` | `4b4c96f` |

---

## Remaining Tasks (Ordered by Priority)

### TASK-001: Migrate EventStore to Async

**Risk:** MEDIUM  
**Effort:** 4 hours  
**Dependencies:** None

**Problem:** `weebot/infrastructure/event_store.py` uses synchronous `sqlite3` connections wrapped in `asyncio.to_thread()`. Each call opens/closes a new connection. Under high concurrency, the thread pool can be exhausted.

**Required Changes:**

1. Replace `sqlite3.connect()` with the existing `SQLiteConnectionPool` from `weebot/infrastructure/persistence/connection_pool.py`
2. Remove synchronous methods (`_sync_log_event`, `_sync_get_session_events`, etc.)
3. Make all public methods truly async using `aiosqlite`
4. Remove `asyncio.to_thread` wrappers

**Implementation Steps:**

```python
# Step 1: Change constructor to accept pool or create one
def __init__(self, db_path: str = "~/.weebot/events.db", pool: Optional[SQLiteConnectionPool] = None):
    self.db_path = Path(db_path).expanduser()
    self.db_path.parent.mkdir(parents=True, exist_ok=True)
    self._pool = pool  # Use shared pool if provided
    self._owns_pool = pool is None
```

```python
# Step 2: Convert _get_connection to use pool
async def _get_connection(self):
    """Get a database connection from the pool."""
    if self._pool is None:
        self._pool = await get_or_create_pool(self.db_path, max_read_connections=3)
    return self._pool
```

```python
# Step 3: Make log_event truly async
async def log_event(self, session_id, event_type, data, ...):
    pool = await self._get_connection()
    async with pool.acquire_write() as conn:
        cursor = await conn.execute(
            "INSERT INTO events (...) VALUES (...)", [...]
        )
        return cursor.lastrowid
```

**Acceptance Criteria:**
- All existing EventStore tests pass
- No `asyncio.to_thread` calls remain in event_store.py
- Event store operations work without thread pool consumption

**Regression Tests:**
- `test_event_store_basic_operations` (create, read, update, delete)
- `test_event_store_concurrent_access` (10 concurrent log_event calls)
- `test_event_store_cost_summary` (verify cost tracking still accurate)

**Rollback:** `git checkout weebot/infrastructure/event_store.py`

---

### TASK-002: Add Schema Migration System

**Risk:** MEDIUM  
**Effort:** 3 hours  
**Dependencies:** None (Alembic already in requirements.txt)

**Problem:** All database tables use `CREATE TABLE IF NOT EXISTS`. Schema changes (new columns, altered indexes) require manual database deletion.

**Required Changes:**

1. Initialize Alembic: `alembic init alembic`
2. Create initial migration from current schema
3. Replace `CREATE TABLE IF NOT EXISTS` calls with a version check
4. Add `alembic upgrade head` to application startup

**Implementation Steps:**

1. Run `alembic init migrations` in project root
2. Configure `env.py` to use the SQLite database path from settings
3. Generate initial migration:
   ```bash
   alembic revision --autogenerate -m "initial schema"
   ```
4. Add migration to startup in `create_app()`:
   ```python
   from alembic.config import Config
   from alembic import command
   alembic_cfg = Config("alembic.ini")
   command.upgrade(alembic_cfg, "head")
   ```

**Acceptance Criteria:**
- `alembic history` shows clean migration chain
- Fresh database auto-migrates on first startup
- Adding a new column and running `alembic upgrade head` works

**Risk:** Medium — Alembic with SQLite has limitations (no ALTER COLUMN, no DROP COLUMN). Test on a copy of production data first.

---

### TASK-003: Persist Circuit Breaker State

**Risk:** LOW  
**Effort:** 2 hours  
**Dependencies:** TASK-001 (for clean DB access)

**Problem:** Circuit breaker state is in-memory only. On restart, all breakers reset to CLOSED, causing an initial burst of failures to failing models.

**Required Changes:**

1. Add `circuit_breaker_state` table to the EventStore or StateRepo database
2. On `record_failure()` / `record_success()`, persist state changes
3. On startup, load persisted breaker states
4. Honor remaining cooldown time for OPEN breakers

**Implementation:**

```python
# In CircuitBreaker
async def persist(self, state_repo):
    """Flush all breaker states to storage."""
    for entity_id, entry in self._breakers.items():
        await state_repo.save_breaker_state(BreakerStateData(
            entity_id=entity_id,
            state=entry.state.value,
            failure_count=entry.failure_count,
            last_failure_time=entry.last_failure_time,
            last_state_change=entry.last_state_change,
        ))

async def load(self, state_repo):
    """Restore breaker states from storage."""
    for state_data in await state_repo.list_breaker_states():
        entry = _BreakerEntry()
        entry.state = BreakerState(state_data.state)
        entry.failure_count = state_data.failure_count
        entry.last_failure_time = state_data.last_failure_time
        entry.last_state_change = state_data.last_state_change
        self._breakers[state_data.entity_id] = entry
```

**Acceptance Criteria:**
- After 3 failures, breaker opens. After restart, breaker is still open.
- After cooldown period (even across restart), breaker transitions to HALF_OPEN.
- Database query for breaker state is < 5ms.

**Rollback:** Remove persistence code; breakers revert to in-memory only.

---

### TASK-004: Decompose PlanActFlow

**Risk:** MEDIUM  
**Effort:** 8 hours  
**Dependencies:** None (but recommend doing after TASK-001-003)

**Problem:** PlanActFlow has 30+ constructor parameters, a 350-line `__init__`, and handles 10+ distinct responsibilities.

**Required Changes:**

Extract three collaborators:

1. **`EventEmitter`** — handles `_emit()`, credential sanitization, truth binding, domain event publishing, hook execution
2. **`FlowPersistence`** — handles `_maybe_save_checkpoint()`, `_get_persistence_adapter()`, session persistence in `_emit()`
3. **`ModelSelector`** — handles `_maybe_switch_model_for_context()`, `_update_agents_with_model()`

**Implementation Steps:**

1. Create `weebot/application/flows/collaborators/` directory
2. Extract EventEmitter with all event-related logic
3. Extract FlowPersistence with all persistence-related logic
4. Extract ModelSelector with all model-switching logic
5. Reduce PlanActFlow to: delegate to collaborators, sequence state transitions

**Acceptance Criteria:**
- PlanActFlow constructor has ≤ 10 parameters (down from 30+)
- All existing flow tests pass unchanged
- Each collaborator has its own unit tests
- `test_plan_act_flow.py` tests are simpler (fewer mocks needed)

**Rollback:** `git revert` the decomposition commit.

---

## Task Dependency Order

```
TASK-001 (EventStore async) ─┐
                              ├──→ TASK-003 (Circuit breaker persistence)
TASK-002 (Alembic migrations) ─┘
                              │
TASK-004 (PlanActFlow decomp) ─┘ (no dependency)
```

**Execution order:**
1. TASK-001 (EventStore async) — 4h
2. TASK-002 (Alembic migrations) — 3h (parallel with TASK-001)
3. TASK-003 (Circuit breaker persistence) — 2h (depends on TASK-001/002)
4. TASK-004 (PlanActFlow decomposition) — 8h (independent)

---

## Validation Checklist

Before deployment:
- [ ] `python -m pytest tests/ -v --tb=short` — all tests pass
- [ ] `python -m cli.main health` — health check passes
- [ ] `python -c "from weebot.interfaces.web.main import create_app; app = create_app()"` — FastAPI app creates
- [ ] `alembic upgrade head` — migrations run clean
- [ ] Manual test: Start server, create session, verify persistence
- [ ] Manual test: Kill server, restart, verify session loaded

## Post-Deployment Monitoring

- [ ] `llm_calls_total` — verify caching works (cache hits increasing)
- [ ] `circuit_breaker_state_changes` — verify breakers activate/deactivate
- [ ] `event_bus_publish_duration_seconds` — verify no regression in event latency
- [ ] Error rate on session persistence — should be 0
