# Code Review Fixes Plan — 2026-06-12

Addresses all 19 findings from the post-session code review (3 CRITICAL, 6 HIGH,
5 MEDIUM, 5 LOW).  Fixes are ordered by severity first, then by dependency:
changes to a shared module appear before changes in modules that import it.

---

## Implementation Order

| # | Severity | File | Description |
|---|----------|------|-------------|
| 1 | CRITICAL | `interfaces/web/main.py` | Add missing `LLMPort` import |
| 2 | CRITICAL | `interfaces/web/routers/sessions.py` | Add missing `http_request` param to `cancel_session` |
| 3 | CRITICAL | `interfaces/web/main.py` | Fix unbound `_m` in global exception handler |
| 4 | HIGH | `interfaces/web/main.py` | Fix XSS in WebSocket test UI (`innerHTML` → DOM safe) |
| 5 | HIGH | `infrastructure/event_store.py` | Refactor `_ensure_schema` to eliminate re-entrant call |
| 6 | HIGH | `infrastructure/event_store.py` | Add `INSERT OR IGNORE` sessions upsert guard in `log_event` |
| 7 | HIGH | `infrastructure/adapters/apify/apify_service.py` | Validate actor_id / run_id / dataset_id before URL embedding |
| 8 | HIGH | `infrastructure/persistence/sqlite_state_repo.py` | `_fts5_indexed`: class var → instance var |
| 9 | HIGH | `application/flows/plan_act_flow.py` | Fix `_get_persistence_adapter` / `_get_tracing_port` using wrong Container |
| 10 | MEDIUM | `core/circuit_breaker.py` | Normalise `last_failure_time` as monotonic offset on serialise |
| 11 | MEDIUM | `interfaces/web/routers/sessions.py` | Teardown ApifyService on failed `run_session` |
| 12 | MEDIUM | `infrastructure/persistence/sqlite_state_repo.py` | `update_session_status`: use `rowcount`, remove full `load_session` |
| 13 | MEDIUM | `infrastructure/persistence/sqlite_state_repo.py` | `delete_session`: use `COUNT(*)` check instead of full `load_session` |
| 14 | MEDIUM | `infrastructure/persistence/sqlite_state_repo.py` | `search_sessions`: cap query length at 500 chars |
| 15 | LOW | `infrastructure/persistence/sqlite_state_repo.py` | Move `behavioral_rules` DDL into `_ensure_schema` |
| 16 | LOW | `infrastructure/event_store.py` | `cleanup_old_sessions`: batch DELETEs to avoid N+1 |
| 17 | LOW | `interfaces/web/main.py` | Replace f-string log calls with `%s` style |
| 18 | LOW | `interfaces/web/routers/sessions.py` | Replace f-string log calls; remove stale TODO comments |

---

## Fix C1 — Missing `LLMPort` import in `main.py`

**File**: `weebot/interfaces/web/main.py`  
**Lines affected**: import block (~line 18); usage at lines 158 and 175

**Problem**: Both the startup and shutdown branches of `lifespan()` call
`container.get(LLMPort)`, but `LLMPort` is never imported.  The surrounding
`except Exception` swallows the `NameError`, so circuit-breaker state is silently
never saved or restored.

**Fix**: Add one import alongside the existing port imports.

```python
# After line 19 ("from weebot.application.ports.metrics_port import MetricsPort")
from weebot.application.ports.llm_port import LLMPort
```

No other changes needed — the usage on lines 158 and 175 is correct once the
name is in scope.

---

## Fix C2 — `cancel_session` missing `http_request: Request` parameter

**File**: `weebot/interfaces/web/routers/sessions.py`  
**Lines affected**: 118–152

**Problem**: Line 132 does `container = request.app.state.container`, but
`request` is not in the function signature.  Every `POST /api/sessions/{id}/cancel`
call raises `NameError: name 'request' is not defined`.

**Fix**: Add `http_request: Request` to the signature (matching the convention
used in `run_session`), then reference `http_request.app.state.container`.

```python
# BEFORE
@router.post("/{session_id}/cancel")
async def cancel_session(
    session_id: str,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> SessionResponse:

# AFTER
@router.post("/{session_id}/cancel")
async def cancel_session(
    session_id: str,
    http_request: Request,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> SessionResponse:
```

Replace the single reference on line 132:
```python
# BEFORE
container = request.app.state.container
# AFTER
container = http_request.app.state.container
```

---

## Fix C3 — Unbound `_m` in global exception handler

**File**: `weebot/interfaces/web/main.py`  
**Lines affected**: 252–256

**Problem**: The comment says "lazy import" but no import statement exists.
`_m` is unbound, so `_m.exceptions_total.labels(...).inc()` raises `NameError`
on every unhandled exception.  Prometheus counter never increments.

**Fix**: Add the lazy import inside the `try` block.

```python
# BEFORE
try:
    # Lazy import: metrics are imported inside exception handler
    _m.exceptions_total.labels(exception_type=type(exc).__name__).inc()
except Exception:
    pass

# AFTER
try:
    from weebot.infrastructure.observability import metrics as _m
    _m.exceptions_total.labels(exception_type=type(exc).__name__).inc()
except Exception:
    pass
```

---

## Fix H4 — XSS in WebSocket test UI (`innerHTML`)

**File**: `weebot/interfaces/web/main.py`  
**Line affected**: 120

**Problem**: `div.innerHTML = \`<strong>${type}:</strong> <pre>${content}</pre>\``
— both `type` and `content` come from WebSocket JSON and are rendered as raw HTML.
A crafted payload can inject `<script>` or event handlers.  The page is served at
the root path with no access controls.

**Fix**: Use safe DOM methods.  `type` is a string from `JSON.parse`; `content`
is the result of `JSON.stringify` (which escapes quotes but not `<>`).

```javascript
// BEFORE (line 120)
div.innerHTML = `<strong>${type}:</strong> <pre>${content}</pre>`;

// AFTER
const strong = document.createElement('strong');
strong.textContent = type + ':';
const pre = document.createElement('pre');
pre.textContent = content;
div.appendChild(strong);
div.appendChild(document.createTextNode(' '));
div.appendChild(pre);
```

---

## Fix H5 — `_ensure_schema` re-entrant call in `event_store.py`

**File**: `weebot/infrastructure/event_store.py`  
**Lines affected**: 108–157

**Problem**: `_get_pool()` calls `_ensure_schema()`, which calls `_get_pool()`
again.  The recursion terminates by accident (because `self._pool` is set before
`_ensure_schema` is called), but if `get_or_create_pool` raises after partial
assignment, `self._pool` may be left in a broken state.

**Fix**: Pass the pool object directly to `_ensure_schema` so it never needs to
call `_get_pool`.

```python
async def _get_pool(self):
    """Lazy-init connection pool."""
    if self._pool is None:
        from weebot.infrastructure.persistence.connection_pool import get_or_create_pool
        pool = await get_or_create_pool(
            self.db_path, max_read_connections=3, enable_wal=True,
        )
        await self._ensure_schema(pool)   # pass pool — no re-entrant call
        self._pool = pool                  # assign only after schema is ready
    return self._pool

async def _ensure_schema(self, pool) -> None:   # pool is a parameter, not resolved via _get_pool
    """Create tables if they don't exist."""
    async with pool.acquire_write() as conn:
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions ( ... );
            CREATE TABLE IF NOT EXISTS events ( ... );
            ...
            """
        )
```

This also improves startup correctness: `self._pool` is only set after the schema
is confirmed good, so a concurrent caller that races `_get_pool` before schema
creation finishes will wait (if using an async lock) or re-enter the init
branch — either is safer than a half-initialised pool.

---

## Fix H6 — Add `INSERT OR IGNORE` sessions guard in `log_event`

**File**: `weebot/infrastructure/event_store.py`  
**Lines affected**: 174–189

**Problem**: `log_event` inserts an event row and then tries to
`UPDATE sessions SET total_cost = ... WHERE id = ?`.  If `start_session` was
never called, the `UPDATE` silently updates zero rows — cost and token totals
are permanently lost.

**Fix**: Add an upsert guard before the `INSERT INTO events`.

```python
async def log_event(self, session_id, event_type, data, cost=0.0, model="", tokens_used=0):
    pool = await self._get_pool()
    async with pool.acquire_write() as conn:
        # Ensure a parent sessions row exists so the UPDATE below is never a no-op.
        await conn.execute(
            "INSERT OR IGNORE INTO sessions (id, started_at, status) "
            "VALUES (?, datetime('now'), 'active')",
            (session_id,),
        )
        cursor = await conn.execute(
            "INSERT INTO events (session_id, event_type, data_json, cost, model, tokens_used) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, event_type, json.dumps(data), cost, model, tokens_used),
        )
        await conn.execute(
            "UPDATE sessions SET total_cost = total_cost + ?, total_tokens = total_tokens + ? "
            "WHERE id = ?",
            (cost, tokens_used, session_id),
        )
        return cursor.lastrowid
```

---

## Fix H7 — Validate actor_id / run_id / dataset_id in `apify_service.py`

**File**: `weebot/infrastructure/adapters/apify/apify_service.py`  
**Lines affected**: 109–146

**Problem**: `actor_id.replace("/", "~")` only normalises the slash; it does not
prevent `../`, `%2e`, query metacharacters (`?#&`), or other URL control
characters.  `run_id` and `dataset_id` are also embedded directly.

**Fix**: Add module-level compiled regexes and validate all three identifier
types before constructing the URL.  Format constraints come from the Apify API
documentation: actor IDs are `owner/name` (alphanumeric, dashes, underscores),
run IDs and dataset IDs are hex strings.

```python
import re as _re

_ACTOR_ID_RE = _re.compile(r'^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$')
_RUN_OR_DATASET_ID_RE = _re.compile(r'^[a-zA-Z0-9]{15,30}$')


def _validate_actor_id(actor_id: str) -> None:
    if not _ACTOR_ID_RE.match(actor_id):
        raise ValueError(f"Invalid actor_id format: {actor_id!r}")


def _validate_resource_id(rid: str, name: str) -> None:
    if not _RUN_OR_DATASET_ID_RE.match(rid):
        raise ValueError(f"Invalid {name} format: {rid!r}")
```

In `_run_actor_sync` and `_run_actor`, replace:
```python
url_id = actor_id.replace("/", "~")
```
with:
```python
_validate_actor_id(actor_id)
url_id = actor_id.replace("/", "~")
```

In `_get_run`:
```python
_validate_resource_id(run_id, "run_id")
```

In `_get_dataset_items`:
```python
_validate_resource_id(dataset_id, "dataset_id")
```

Callers that pass invalid identifiers will receive a `ValueError` which
`execute()` should catch and convert to a `ServiceResponse(success=False, ...)`:
wrap each `await handler(**kwargs)` call with a `ValueError` guard:

```python
try:
    return await handler(**kwargs)
except ValueError as exc:
    return ServiceResponse(success=False, error=str(exc), status_code=400)
```

---

## Fix H8 — `_fts5_indexed`: class variable → instance variable

**File**: `weebot/infrastructure/persistence/sqlite_state_repo.py`  
**Line affected**: 341

**Problem**: `_fts5_indexed: dict[str, int] = {}` is a class-level attribute,
shared across all instances.  Instance A marks session X as indexed; instance B
(e.g., in a test or after DI re-wiring) sees the same dict and skips re-indexing
events it hasn't actually indexed yet.

**Fix**: Initialise in `__init__` as an instance attribute.

Locate the `__init__` of `SQLiteStateRepository` and add:
```python
self._fts5_indexed: dict[str, int] = {}
```
Remove the class-level definition on line 341.

---

## Fix H9 — `_get_persistence_adapter` / `_get_tracing_port` use wrong Container

**File**: `weebot/application/flows/plan_act_flow.py`  
**Lines affected**: 564–576 (`_get_persistence_adapter`), 621–629 (`_get_tracing_port`)

**Problem**: Both methods create `Container()` — a fresh, unconfigured instance.
The adapter registered in the actual app container (`app.state.container`) is
never found, so `_persistence_adapter` is permanently `None` and checkpoints
are silently disabled.  Same for tracing.

**Architectural note**: `PlanActFlow` lives in the Application layer.  It must
not import from `weebot.application.di` (Container is Application-layer
infrastructure).  The correct approach is constructor injection: accept optional
ports at construction time.  If a port is not provided, it stays `None` (graceful
degradation), rather than trying to self-resolve from an ad-hoc container.

**Fix**:

1. Add two optional constructor parameters (already in the signature as private
   attrs — surface them):

```python
def __init__(
    self,
    ...
    checkpoint_port: Optional[CheckpointPort] = None,
    tracing_port: Optional[TracingPort] = None,
    persistence_adapter = None,   # CheckpointPort or SessionPersistencePort
) -> None:
    ...
    self._checkpoint_port = checkpoint_port
    self._tracing_port = tracing_port
    self._persistence_adapter = persistence_adapter
```

2. Remove `_get_persistence_adapter` and `_get_tracing_port` methods entirely.
   Replace every call site with direct attribute access (already nullable —
   existing None-checks in callers remain correct).

3. The call site in `run_session` (web router) already passes `llm`, `tools`,
   and `event_bus`; it should also resolve and pass `checkpoint_port` and
   `tracing_port` from the app container when creating the factory.

---

## Fix M1 — Normalise `last_failure_time` as monotonic offset in `circuit_breaker.py`

**File**: `weebot/core/circuit_breaker.py`  
**Lines affected**: 370–398

**Problem**: `last_state_change` is correctly serialised as an offset from
`time.monotonic()` so it survives restarts.  `last_failure_time` is a raw
monotonic value that becomes meaningless after restart — restored verbatim,
it will read as a timestamp from a different epoch.

**Fix**: Apply the same offset transform to `last_failure_time`.

In `to_persistable()`:
```python
"last_failure_time_offset": now - entry.last_failure_time if entry.last_failure_time else None,
```
(remove `"last_failure_time": entry.last_failure_time`)

In `load_from_persistable()`:
```python
_lft_offset = s.get("last_failure_time_offset")
last_failure_time = now - _lft_offset if _lft_offset is not None else 0.0
entry = _BreakerEntry(
    ...
    last_failure_time=last_failure_time,
    ...
)
```

Add backward-compat: if the old `"last_failure_time"` key is present (no
`"last_failure_time_offset"`), treat it as 0.0 so existing state files don't
crash on restore.

---

## Fix M2 — Teardown `ToolCollection` on failed `run_session`

**File**: `weebot/interfaces/web/routers/sessions.py`  
**Lines affected**: 219–229

**Problem**: `build_tools()` initialises `ApifyService` (two open
`aiohttp.ClientSession` objects).  If `task_runner.start_session()` raises,
the except block re-raises as HTTPException without calling `tools.teardown()`.
The aiohttp sessions leak for the life of the process.

**Fix**: Ensure teardown in the error path.

```python
tools = await build_tools(role="admin")
try:
    factory = task_runner.create_plan_act_factory(
        llm=llm, tools=tools, event_bus=event_bus, model=model
    )
    session = await task_runner.start_session(session, factory)
except Exception as exc:
    await tools.teardown()     # ← prevent session leak
    logger.exception("Failed to start session %s: %s", session_id, exc)
    raise HTTPException(status_code=500, detail=f"Failed to start task: {exc}")
```

---

## Fix M3 — `update_session_status`: use `rowcount`, remove `load_session` round trip

**File**: `weebot/infrastructure/persistence/sqlite_state_repo.py`  
**Lines affected**: 260–281

**Problem**: After the `UPDATE`, a full `load_session()` call (which
deserialises the entire events JSON blob) is made just to check whether the
update actually changed a row.  `cursor.rowcount` is available and sufficient.

**Fix**:

```python
async with pool.acquire_write() as conn:
    cursor = await conn.execute(
        "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
        (status.value, datetime.now(timezone.utc).isoformat(), session_id),
    )
    updated = cursor.rowcount > 0
if updated:
    logger.debug("Session %s status updated to %s", session_id, status.value)
return updated
```

Remove the `await self.load_session(session_id)` call and the associated import
comment ("Note: aiosqlite doesn't expose rowcount easily").  It does.

---

## Fix M4 — `delete_session`: existence check via `COUNT(*)`, not `load_session`

**File**: `weebot/infrastructure/persistence/sqlite_state_repo.py`  
**Lines affected**: 283–311

**Problem**: `existing = await self.load_session(session_id)` deserialises the
entire session (potentially megabytes of events JSON) just to get a bool.

**Fix**: Use a cheap existence query.

```python
async def delete_session(self, session_id: str) -> bool:
    pool = await self._get_pool()
    row = await pool.execute_read(
        "SELECT COUNT(*) as cnt FROM sessions WHERE id = ?",
        (session_id,),
        fetch_all=False,
    )
    if not row or row["cnt"] == 0:
        return False
    async with pool.acquire_write() as conn:
        await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    # Clear FTS5 index
    try:
        from weebot.infrastructure.persistence.fts5_search import clear_session_events
        async with pool.acquire_write() as conn:
            await clear_session_events(conn, session_id)
    except Exception:
        pass
    logger.debug("Session deleted: %s", session_id)
    return True
```

Note: events are FK-cascade deleted or must be explicitly deleted too.  Check
whether `PRAGMA foreign_keys = ON` is set in the connection pool; if not, add
`DELETE FROM sessions_events WHERE session_id = ?` before the session delete
(similar to how `AsyncEventStore.delete_session` already does it explicitly).

---

## Fix M5 — `search_sessions`: cap query length to prevent tokeniser overload

**File**: `weebot/infrastructure/persistence/sqlite_state_repo.py`  
**Lines affected**: 313–318

**Problem**: An unbounded query string is passed directly to the FTS5 tokeniser,
which may do quadratic work on very long inputs.

**Fix**: Truncate the query before passing it downstream.

```python
async def search_sessions(self, query: str, limit: int = 20) -> list[dict]:
    """Full-text search across all indexed sessions (M2)."""
    query = query[:500]   # prevent FTS5 tokeniser overload
    from weebot.infrastructure.persistence.fts5_search import search_events
    pool = await self._get_pool()
    return await search_events(pool, query, limit=limit)
```

---

## Fix L1 — Move `behavioral_rules` DDL into `_ensure_schema`

**File**: `weebot/infrastructure/persistence/sqlite_state_repo.py`  
**Lines affected**: 394–408 (`save_behavioral_rule`), 432–447 (`list_behavioral_rules`)

**Problem**: `CREATE TABLE IF NOT EXISTS behavioral_rules` is executed inside
both read and write DML methods, generating unnecessary DDL on every call.

**Fix**: Add the `behavioral_rules` DDL to the `_ensure_schema` block (which
runs once at pool initialisation).  Remove the inline `CREATE TABLE IF NOT EXISTS`
blocks from both `save_behavioral_rule` and `list_behavioral_rules`.

In `_ensure_schema`, add after the existing session/event tables:

```sql
CREATE TABLE IF NOT EXISTS behavioral_rules (
    id TEXT PRIMARY KEY,
    rule_text TEXT NOT NULL,
    source_session_id TEXT NOT NULL DEFAULT '',
    source_message TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT 'global',
    created_at TEXT NOT NULL,
    applied_count INTEGER NOT NULL DEFAULT 0,
    last_applied_at TEXT
);
```

---

## Fix L2 — `cleanup_old_sessions`: batch DELETE, eliminate N+1

**File**: `weebot/infrastructure/event_store.py`  
**Lines affected**: 403–418

**Problem**: Current implementation fetches a list of session IDs and calls
`delete_session()` in a Python loop — two SQL statements per session.

**Fix**: Replace with two batch DELETEs.

```python
async def cleanup_old_sessions(self, days: int = 30) -> int:
    if not isinstance(days, int) or days < 0:
        raise ValueError(f"days must be a non-negative integer, got {days}")
    pool = await self._get_pool()
    modifier = f"-{days} days"
    async with pool.acquire_write() as conn:
        # Delete events for old sessions first (FK consistency)
        await conn.execute(
            "DELETE FROM events WHERE session_id IN "
            "(SELECT id FROM sessions WHERE started_at < datetime('now', ?))",
            (modifier,),
        )
        cursor = await conn.execute(
            "DELETE FROM sessions WHERE started_at < datetime('now', ?)",
            (modifier,),
        )
        return cursor.rowcount
```

---

## Fix L3/L4 — Log style consistency and stale TODOs

**Files**:
- `weebot/interfaces/web/main.py` lines 305, 313, 332, 339
- `weebot/interfaces/web/routers/sessions.py` lines 50, 53, 83, 113, 151, 179

**Fix**: Replace `logger.info(f"msg {var}")` with `logger.info("msg %s", var)`.
Remove the two stale `# TODO` lines (lines 50 and 53 in sessions.py) — the code
already uses `Depends(get_state_repo)` for DI, making them obsolete.

---

## Verification

After all fixes, run in this order:

```bash
# 1. Unit tests (cover persistence, event_store, circuit_breaker, apify validation)
pytest tests/unit/ -v -x

# 2. Security-focused tests
pytest tests/unit/test_adversarial_security.py tests/unit/test_audit_findings.py -v

# 3. Start the web server and smoke-test the three CRITICAL endpoints
python -m weebot.interfaces.web.main &
curl -s http://localhost:8000/api/health           # should return 200
curl -s -X POST http://localhost:8000/api/sessions/nonexistent/cancel  # 404, not 500
# (verify no NameError in server logs)

# 4. (Optional) Confirm Prometheus counter increments on a forced error
```

For Fix H7 (Apify validation), add unit tests:
```python
# In tests/unit/test_apify_service.py
def test_invalid_actor_id_raises():
    svc = ApifyService()
    # actor_id with path traversal attempt
    with pytest.raises(ValueError, match="Invalid actor_id"):
        svc._validate_actor_id("../../etc/passwd")

def test_valid_actor_id_passes():
    svc._validate_actor_id("apify/web-scraper")  # no exception
```

---

## Architecture Notes

- **Fix H9** (Container injection in PlanActFlow) is the most architecturally
  significant change.  `PlanActFlow` is in the Application layer and must only
  receive dependencies through constructor injection — never by creating its own
  Container.  The refactor moves in the right direction but requires the web
  router (`run_session`) to pass the resolved ports.  Coordinate with the DI
  container's `create_plan_act_factory` so it injects the ports from the app's
  live container, not a fresh one.

- **Fix H5 + Fix H6** (event_store schema init) should be reviewed together —
  they touch the same `_get_pool` / `_ensure_schema` methods.

- **Fix L1** (behavioral_rules DDL) requires confirming that `_ensure_schema`
  is always called before any behavioral_rules read or write.  After Fix H5 this
  is guaranteed because schema init completes before `self._pool` is assigned.

- All fixes are purely additive or internal to individual modules — no new
  public API surfaces, no dependency inversion changes (except Fix H9).
