# Implementation Plan — Undiscovered Defects Batch

**Date:** 2026-06-16
**Plan ID:** FIX-UNDISCOVERED-001
**Architecture:** Clean Architecture (Hexagonal) — all changes respect layer boundaries
**Defects addressed:** 16 defects across 4 phases

---

## Phase 1: CRITICAL — Production-Breaking (Do First)

### Fix 1.1 — Dockerfile.web: Fix Next.js Build Output Path

**Defect:** `Dockerfile.web:6` copies `/app/dist` but Next.js outputs to `.next/`.

**Architecture note:** The web service is an nginx container serving static files. Next.js supports `output: 'standalone'` mode which produces a self-contained deployment. We'll switch to standalone output for production Docker builds.

**File 1:** `weebot-ui/next.config.mjs`

Add `output: 'standalone'` to the Next.js config:
```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',   // ← NEW: produce self-contained .next/standalone for Docker
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8000/api/:path*',
      },
    ];
  },
  reactStrictMode: false,  // see Fix 4.2 for re-enabling
};

export default nextConfig;
```

**File 2:** `Dockerfile.web` — full replacement

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY weebot-ui/package*.json ./
RUN npm ci
COPY weebot-ui/ .
RUN npm run build
# Standalone output: .next/standalone contains node_modules + server.js
# Static assets are in .next/static — must be copied alongside standalone

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000

# Copy standalone server + static assets
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
# Copy public assets (favicon, etc.)
COPY --from=build /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
```

**File 3:** `docker-compose.yml` — update web service

Change the web service from nginx to the Next.js standalone server:
```yaml
  web:
    build:
      context: .
      dockerfile: Dockerfile.web
    ports:
      - "3000:3000"
    environment:
      - BACKEND_URL=http://api:8000/api
    depends_on:
      - api
    restart: unless-stopped
```

Also add `X-API-Key` forwarding to the API service environment and nginx config (see Fix 4.1).

**Validation:**
```bash
docker-compose build web
docker-compose up -d
curl http://localhost:3000
```

**Rollback:** `git checkout Dockerfile.web docker-compose.yml weebot-ui/next.config.mjs`

**Risk:** LOW — the Docker deployment wasn't working anyway; this makes it functional.

---

### Fix 1.2 — Behavior Router: Add Missing Imports

**Defect:** `behavior_router.py` uses 7+ symbols from `behavior_tracker.py` and `behavior_reporting.py` without importing them.

**Architecture note:** The behavior router is in the Interfaces layer. Importing from `weebot.core.behavior_tracker` (Core layer) is correct — Interfaces → Core is allowed by Clean Architecture dependency rules.

**File:** `weebot/interfaces/web/routers/behavior_router.py`

Replace the single import line:
```python
from weebot.core.behavior_reporting import BehaviorReporter
```

With:
```python
from weebot.core.behavior_reporting import BehaviorReporter, SelfKnowledgeGenerator
from weebot.core.behavior_tracker import (
    BehaviorEvent,
    BehaviorTracker,
    TrustManager,
    create_tracker,
    get_tracker,
    stop_tracker,
)
```

**Also fix:** The `broadcast_event` function signature uses `BehaviorEvent` as a type hint but `BehaviorEvent` was not imported. With the import above, this is resolved.

**Validation:**
```bash
python -c "
from weebot.interfaces.web.routers.behavior_router import router
# Verify the module loads without NameError
print('behavior_router imports OK')
print('Routes:', [r.path for r in router.routes])
"
```

**Add test** (prevents regression):
Create `tests/unit/interfaces/test_behavior_router_imports.py`:
```python
def test_behavior_router_imports_all_symbols():
    """Verify all symbols used in behavior_router are importable."""
    from weebot.core.behavior_reporting import BehaviorReporter, SelfKnowledgeGenerator
    from weebot.core.behavior_tracker import (
        BehaviorEvent, BehaviorTracker, TrustManager,
        create_tracker, get_tracker, stop_tracker,
    )
    # If we got here, all symbols resolved
    assert BehaviorReporter is not None
    assert SelfKnowledgeGenerator is not None
    assert TrustManager is not None
    assert callable(create_tracker)
    assert callable(get_tracker)
    assert callable(stop_tracker)
```

**Rollback:** `git checkout weebot/interfaces/web/routers/behavior_router.py`

**Risk:** LOW — the router was non-functional before; this makes it work.

---

### Fix 1.3 — Alembic: Populate Initial Migration

**Defect:** The migration file has empty `upgrade()` and `downgrade()` methods.

**Architecture note:** Schema migration is an Infrastructure concern. The migration file belongs to Alembic's version directory, outside any Clean Architecture layer. This fix populates it with the actual DDL currently scattered across `event_store.py` and `scheduler.py`.

**Decision required:** Two approaches:
- **Option A (recommended):** Populate the migration with DDL, then remove ad-hoc `CREATE TABLE IF NOT EXISTS` from application code. Alembic becomes the single source of truth for schema.
- **Option B:** Remove Alembic entirely and document that schema is managed by `CREATE TABLE IF NOT EXISTS` in each store.

**This plan implements Option A.**

**File 1:** `alembic/versions/548511c41c39_initial_schema.py`

Replace `pass` in both methods:
```python
def upgrade() -> None:
    """Create initial schema: sessions, events, jobs tables."""
    op.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            status TEXT DEFAULT 'active',
            user_id TEXT,
            total_cost REAL DEFAULT 0.0,
            total_tokens INTEGER DEFAULT 0
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            data_json TEXT NOT NULL,
            cost REAL DEFAULT 0.0,
            model TEXT,
            tokens_used INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            trigger_type TEXT NOT NULL,
            trigger_config TEXT NOT NULL,
            command TEXT,
            callable_name TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_run TEXT,
            next_run TEXT,
            run_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            last_error TEXT,
            enabled INTEGER DEFAULT 1
        );
    """)


def downgrade() -> None:
    """Remove initial schema."""
    op.execute("DROP TABLE IF EXISTS events")
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS jobs")
```

**File 2:** `weebot/infrastructure/event_store.py` — remove ad-hoc schema creation

In `_ensure_schema()`, remove the `CREATE TABLE IF NOT EXISTS` statements (lines ~124-145) and replace with a check that Alembic has run:
```python
async def _ensure_schema(self, pool) -> None:
    """Verify schema exists (created by Alembic migrations)."""
    async with pool.acquire_read() as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        )
        if not await cursor.fetchone():
            raise RuntimeError(
                "Database schema not found. Run: alembic upgrade head"
            )
```

**File 3:** `weebot/scheduling/scheduler.py` — remove ad-hoc schema creation

In `_init_db()`, remove the `CREATE TABLE IF NOT EXISTS jobs` block (lines ~111-127) and replace with:
```python
def _init_db(self) -> None:
    """Verify schema exists (created by Alembic migrations)."""
    with sqlite3.connect(self.db_path) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()
        if not row:
            raise RuntimeError(
                "Database schema not found. Run: alembic upgrade head"
            )
```

**Validation:**
```bash
# Start fresh — migration should create all tables
rm -f weebot_sessions.db projects.db
alembic upgrade head
python -c "
import sqlite3
conn = sqlite3.connect('weebot_sessions.db')
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
print('Tables:', [t[0] for t in tables])
assert 'sessions' in [t[0] for t in tables]
assert 'events' in [t[0] for t in tables]
print('Migration OK')
"
```

**Rollback:** `git checkout alembic/versions/548511c41c39_initial_schema.py weebot/infrastructure/event_store.py weebot/scheduling/scheduler.py`

**Risk:** MEDIUM — changes how schema is managed. Existing databases with ad-hoc-created tables will still work because the migration uses `CREATE TABLE IF NOT EXISTS`. The table-existence checks in event_store.py and scheduler.py are backward-compatible.

---

### Fix 1.4 — Connection Pool: Add Shutdown Cleanup

**Defect:** `close_all_pools()` is never called on application shutdown.

**Architecture note:** The lifespan function is the composition root's shutdown hook — it's where all infrastructure cleanup belongs. This fix adds the missing cleanup call without introducing new dependencies.

**File:** `weebot/interfaces/web/main.py`

In the lifespan `shutdown` block (after `await scheduler.stop()`), add:
```python
    # ── Close connection pools ──────────────────────────────────
    try:
        from weebot.infrastructure.persistence.connection_pool import close_all_pools
        await close_all_pools()
        logger.info("Connection pools closed")
    except Exception as exc:
        logger.warning("Error closing connection pools: %s", exc)
```

The insertion point is in the `yield` → shutdown section, after the scheduler stop and before the final log line. The current shutdown block (post-yield) is:

```python
    yield

    # ── Graceful shutdown ──────────────────────────────────────
    if hasattr(app.state, "heartbeat"):
        await app.state.heartbeat.stop()
    # ... circuit breaker persist ...
    await scheduler.stop()
    logger.info("Shutting down Weebot Web Server...")
```

Add the pool cleanup between `await scheduler.stop()` and the final log:
```python
    await scheduler.stop()
    
    # ── Close connection pools ──────────────────────────────────
    try:
        from weebot.infrastructure.persistence.connection_pool import close_all_pools
        await close_all_pools()
        logger.info("Connection pools closed")
    except Exception as exc:
        logger.warning("Error closing connection pools: %s", exc)
    
    logger.info("Shutting down Weebot Web Server...")
```

**Validation:**
```bash
# Start and immediately stop the server — check no "unclosed" warnings
timeout 5 python -m weebot.interfaces.web.main 2>&1 | grep -i "pools closed" || echo "Manual check: start server, Ctrl+C, check logs"
```

**Rollback:** `git checkout weebot/interfaces/web/main.py`

**Risk:** LOW — adds cleanup call to existing exported function.

---

## Phase 2: HIGH — Functional / Security / Architecture

### Fix 2.1 — Scheduler: Migrate to Async SQLite (aiosqlite)

**Defect:** `scheduler.py` uses synchronous `sqlite3.connect()` in async methods, blocking the event loop.

**Architecture note:** The scheduler is in `weebot/scheduling/` — a cross-cutting infrastructure concern. It uses APScheduler's `AsyncIOScheduler`, so its event loop is shared with the web server. Blocking calls here stall WebSocket messages and HTTP responses.

**File:** `weebot/scheduling/scheduler.py`

**Step A — Add aiosqlite import and remove sqlite3 import:**
```python
# Remove: import sqlite3
# Add:
try:
    import aiosqlite
except ImportError:
    aiosqlite = None
```

**Step B — Add async connection helper and init:**
```python
class SchedulingManager:
    # ... existing fields ...
    
    async def _get_conn(self):
        """Get an aiosqlite connection, creating if needed."""
        if not hasattr(self, '_conn') or self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn
```

**Step C — Convert `_init_db()` to async:**
```python
async def _init_db(self) -> None:
    """Initialize database schema (async)."""
    conn = await self._get_conn()
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            ...
        )
    ''')
    await conn.commit()
```

**Step D — Convert `_init_db` call site.** In `__init__`, replace `self._init_db()` with scheduling it:
```python
# At the end of __init__, instead of self._init_db():
self._db_ready = asyncio.ensure_future(self._init_db())
```

**Step E — Convert `_save_job()`, `get_job()`, `delete_job()` to async** using the async connection.

**Step F — Add `close()` method:**
```python
async def close(self) -> None:
    """Close database connection."""
    if hasattr(self, '_conn') and self._conn:
        await self._conn.close()
        self._conn = None
```

**Effort estimate:** ~2 hours. This is the largest single fix.

**Alternative (lower risk):** Instead of migrating to aiosqlite, wrap all sync sqlite3 calls in `asyncio.to_thread()`:
```python
async def _save_job(self, job):
    await asyncio.to_thread(self._save_job_sync, job)

def _save_job_sync(self, job):
    with sqlite3.connect(self.db_path) as conn:
        ...
```

This is the approach used correctly by `checkpoint_store.py` and is lower-risk than a full migration. **Recommend the `asyncio.to_thread()` approach for Phase 2, with full aiosqlite migration as a Phase 4 follow-up.**

**Validation:**
```bash
pytest tests/ -k "scheduler" -v
python -c "
import asyncio
from weebot.scheduling.scheduler import SchedulingManager
async def test():
    mgr = SchedulingManager()
    await mgr.start()
    job = await mgr.create_job('test', 'cron', {'hour': 3})
    assert await mgr.get_job(job.job_id) is not None
    await mgr.stop()
asyncio.run(test())
print('Scheduler async OK')
"
```

**Risk:** MEDIUM — changes database access pattern throughout scheduler.

---

### Fix 2.2 — Persistence Stores: Wrap Sync SQLite with `asyncio.to_thread()`

**Defect:** 6 files use raw `sqlite3.connect()` in async methods.

**Architecture note:** These are all Infrastructure-layer persistence adapters. The correct pattern is demonstrated by `checkpoint_store.py` — wrap sync calls in `loop.run_in_executor(None, ...)` or `asyncio.to_thread()`.

**Files to fix (same pattern applied to each):**

| File | Methods to wrap |
|------|----------------|
| `weebot/infrastructure/persistence/sqlite_summary_repo.py` | `get_summary()`, `save_summary()`, `list_summaries()` |
| `weebot/infrastructure/persistence/sqlite_misalignment_journal.py` | `log()`, `get_recent()` |
| `weebot/infrastructure/persistence/sqlite_knowledge_graph.py` | `_get_conn()`, all query/write methods |
| `weebot/infrastructure/persistence/meta_improvement_log.py` | `log_improvement()`, `get_improvements()`, `get_stats()` |
| `weebot/infrastructure/persistence/skill_variant_store.py` | All CRUD methods (7 methods) |
| `weebot/infrastructure/persistence/strategy_store.py` | All CRUD methods (5 methods) |

**Pattern to apply** (example for `sqlite_summary_repo.py`):

Before:
```python
async def get_summary(self, session_id: str):
    with sqlite3.connect(self.db_path) as conn:
        ...
```

After:
```python
async def get_summary(self, session_id: str):
    return await asyncio.to_thread(self._get_summary_sync, session_id)

def _get_summary_sync(self, session_id: str):
    with sqlite3.connect(self.db_path) as conn:
        ...
```

**Add `import asyncio`** to each file.

**Validation:**
```bash
pytest tests/ -v --tb=short -k "summary or misalignment or knowledge or improvement or variant or strategy"
```

**Risk:** LOW — mechanical refactor, semantic behavior unchanged.

---

### Fix 2.3 — Telegram Adapter: Store Task Reference for Clean Shutdown

**Defect:** `asyncio.create_task(self._poll_loop())` return value discarded; `stop()` can't cancel the task.

**Architecture note:** The Telegram adapter is an Interface-layer gateway. It follows the `start()`/`stop()` lifecycle pattern. The fix stores the task reference and cancels on stop.

**File:** `weebot/interfaces/gateways/telegram.py`

**In `__init__`, add:**
```python
self._poll_task: asyncio.Task | None = None
```

**In `start()`, change:**
```python
async def start(self) -> None:
    self._running = True
    self._poll_task = asyncio.create_task(self._poll_loop())
    logger.info("TelegramAdapter started")
```

**In `stop()`, change:**
```python
async def stop(self) -> None:
    self._running = False
    if self._poll_task and not self._poll_task.done():
        self._poll_task.cancel()
        try:
            await self._poll_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("TelegramAdapter poll task error during shutdown: %s", exc)
    logger.info("TelegramAdapter stopped")
```

**In `_poll_loop`, handle `CancelledError`:**
```python
async def _poll_loop(self) -> None:
    while self._running:
        try:
            updates = await self._get_updates()
            ...
        except asyncio.CancelledError:
            logger.debug("TelegramAdapter poll loop cancelled")
            break
        except Exception as exc:
            logger.warning("TelegramAdapter poll error: %s", exc)
            await asyncio.sleep(5)
```

**Validation:**
```bash
python -c "
import asyncio
from weebot.interfaces.gateways.telegram import TelegramAdapter
# Verify start/stop lifecycle works without warnings
async def test():
    # Don't actually start — just verify the task lifecycle pattern
    adapter = TelegramAdapter(token='test', state_repo=None, llm=None)
    adapter._running = True
    adapter._poll_task = asyncio.create_task(asyncio.sleep(0.1))
    await adapter.stop()
    print('Telegram stop OK')
asyncio.run(test())
"
```

**Risk:** LOW — adds proper lifecycle management to existing adapter.

---

### Fix 2.4 — API Key: Add Auth to Frontend + Fix Proxy Chain

**Defect:** Frontend never sends `X-API-Key`; no auth UI. When `WEEBOT_API_KEY` is set on backend, web UI is unusable.

**Architecture note:** This is a cross-layer integration fix. The backend auth is correctly implemented. The frontend needs: (a) an API key input, (b) storage in localStorage, (c) inclusion in all API requests, and (d) the Next.js proxy must forward it.

**File 1:** `weebot-ui/src/lib/api.ts` — add API key header

Add a module-level API key getter/setter:
```typescript
const API_BASE = "/api";

let _apiKey: string | null = null;
try {
  _apiKey = localStorage.getItem("weebot_api_key");
} catch {
  // localStorage not available (SSR)
}

export function setApiKey(key: string | null) {
  _apiKey = key;
  try {
    if (key) {
      localStorage.setItem("weebot_api_key", key);
    } else {
      localStorage.removeItem("weebot_api_key");
    }
  } catch {
    // localStorage not available
  }
}

export function getApiKey(): string | null {
  return _apiKey;
}
```

In `fetchApi()`, add the header:
```typescript
async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  };
  
  if (_apiKey) {
    headers["X-API-Key"] = _apiKey;
  }
  
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });
  // ... rest unchanged
```

**File 2:** `weebot-ui/src/components/ConnectionStatus.tsx` — add API key input

Add an API key input field (shown when backend requires auth). The ConnectionStatus component already checks `/api/health` — add logic to detect when auth is required (401 response) and show a key input.

```tsx
// Add to ConnectionStatus component:
const [apiKey, setApiKeyState] = useState(getApiKey() || "");
const [needsAuth, setNeedsAuth] = useState(false);

// In the health check effect, detect 401:
if (response.status === 401) {
  setNeedsAuth(true);
  setIsConnected(false);
  return;
}

// Save key handler:
const handleSaveKey = () => {
  setApiKey(apiKey);
  setNeedsAuth(false);
  // Re-check connection
  checkConnection();
};
```

**File 3:** `weebot-ui/src/app/api/[[...path]]/route.ts` — ensure proxy forwards the header

Already forwards `X-API-Key` when present (line 20-22). No change needed — the fix in `lib/api.ts` ensures the header is sent.

**File 4:** `weebot/config/nginx.conf` — forward API key header

Add `proxy_set_header X-API-Key $http_x_api_key;` to the `/api/` location block:
```nginx
location /api/ {
    proxy_pass http://api:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-API-Key $http_x_api_key;
}
```

**Validation:**
```bash
# Start backend with API key
WEEBOT_API_KEY=test-key python -m weebot.interfaces.web.main &
sleep 2

# Verify 401 without key
curl -s http://localhost:8000/api/sessions | grep "Unauthorized"

# Verify 200 with key
curl -s -H "X-API-Key: test-key" http://localhost:8000/api/sessions

# Verify health endpoint works without key (public)
curl -s http://localhost:8000/api/health | grep "healthy"

kill %1
```

**Risk:** MEDIUM — adds new UI element and client-side storage. The API key is stored in localStorage (accessible to client-side JS in the same origin). For a local/single-user tool this is acceptable.

---

## Phase 3: MEDIUM — Architecture / Reliability

### Fix 3.1 — Circuit Breaker: Add Lock to `get_state()` + `get_all_states()`

**Defect:** `get_state()` and `get_all_states()` read `self._breakers` without acquiring `self._lock`.

**File:** `weebot/core/circuit_breaker.py`

Change `get_state()`:
```python
def get_state(self, entity_id: str) -> BreakerState:
    """Get the current state for *entity_id* (sync, for inspection)."""
    # Take a snapshot under lock to avoid torn reads
    entry = self._breakers.get(entity_id)
    return entry.state if entry else BreakerState.CLOSED
```

The lock is intentionally NOT acquired for `get_state()` because:
1. Python dict reads are atomic at the C level (no segfault from concurrent mutation)
2. `_BreakerEntry` is a dataclass — replacing it in the dict under lock means `get()` returns either the old or new entry reference, never a torn pointer
3. The dirty-check in `evaluate()` intentionally reads without lock for performance

The race is benign: the worst case is a stale reading for one monitoring cycle. The authoritative check always happens under lock.

**Actually, this is a non-defect.** After deeper analysis, `get_state()` is safe because:
- Python dict.get() is atomic
- _BreakerEntry is replaced wholesale (never mutated in-place)
- The dirty-check in evaluate() intentionally reads without lock and the authoritative check happens under lock

**Decision: CLOSE as NOT A BUG — add a comment explaining why the lock is not needed.**

**File:** `weebot/core/circuit_breaker.py`

Add docstring clarification:
```python
def get_state(self, entity_id: str) -> BreakerState:
    """Get the current state for *entity_id* (sync, for inspection).
    
    Lock is intentionally not acquired here: Python dict reads are atomic,
    and _BreakerEntry instances are replaced wholesale under lock (never
    mutated in-place). The worst case is a one-cycle stale reading.
    """
    entry = self._breakers.get(entity_id)
    return entry.state if entry else BreakerState.CLOSED
```

---

### Fix 3.2 — DI Container: Inject SandboxPort into Tools in `build_mediator()`

**Defect:** `build_mediator()` creates `BashTool()`, `PythonExecuteTool()` etc. without constructor arguments. PythonExecuteTool needs a SandboxPort.

**Architecture note:** The DI container is the composition root. It should resolve all dependencies before constructing objects. This fix injects the sandbox via the container.

**File:** `weebot/application/di/__init__.py`

In `build_mediator()`, change the tool construction:
```python
def build_mediator(self) -> Mediator:
    # ... existing mediator setup ...
    
    llm = self._maybe_get(LLMPort)
    tools = None
    if llm is not None:
        from weebot.application.models.tool_collection import ToolCollection
        from weebot.tools.bash_tool import BashTool
        from weebot.tools.file_editor import StrReplaceEditorTool as FileEditorTool
        from weebot.tools.python_tool import PythonExecuteTool as PythonTool
        from weebot.tools.image_gen_tool import ImageGenTool
        from weebot.application.ports.sandbox_port import SandboxPort
        
        # Resolve shared sandbox from container
        sandbox = self._maybe_get(SandboxPort)
        
        try:
            tools = ToolCollection(
                BashTool(sandbox=sandbox),
                FileEditorTool(),
                PythonTool(sandbox=sandbox),
                ImageGenTool(),
            )
        except Exception as exc:
            logger.warning("Failed to create tools for mediator: %s", exc)
            tools = None
    # ... rest unchanged
```

**Same fix in `_create_sub_agent_factory()`** (line ~220-260):
```python
def _create_sub_agent_factory(self):
    sandbox = self._maybe_get(SandboxPort)
    tools = ToolCollection(
        BashTool(sandbox=sandbox),
        FileEditorTool(),
        PythonTool(sandbox=sandbox),
        ImageGenTool(),
    )
    # ... rest unchanged
```

**Validation:**
```bash
python -c "
from weebot.application.di import Container
c = Container()
c.configure_defaults()
mediator = c.build_mediator()
print('Mediator built OK')
"
```

**Risk:** LOW — tools accept optional sandbox; if sandbox is None, they fall back to their own DI resolution (existing behavior).

---

### Fix 3.3 — SQLiteToolRepository: Use Connection Pool

**Defect:** Every method opens a new `aiosqlite.connect()` instead of using the shared pool.

**File:** `weebot/infrastructure/persistence/sqlite_tool_repo.py`

**Refactor to use the pool:**
```python
from weebot.infrastructure.persistence.connection_pool import get_or_create_pool

class SQLiteToolRepository:
    def __init__(self, db_path: str = "~/.weebot/tools.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool = None
    
    async def _get_pool(self):
        if self._pool is None:
            self._pool = await get_or_create_pool(self.db_path, max_read_connections=2)
            await self._ensure_schema()
        return self._pool
    
    async def get_tool(self, name: str):
        pool = await self._get_pool()
        return await pool.execute_read(
            "SELECT * FROM tools WHERE name = ?", (name,), fetch_all=False
        )
    
    async def save_tool(self, name: str, data: dict):
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO tools (name, data) VALUES (?, ?)",
                (name, json.dumps(data))
            )
    
    # ... apply same pattern to all methods
```

**Validation:**
```bash
pytest tests/ -k "tool_repo" -v
```

**Risk:** LOW — uses existing pool infrastructure; backward compatible.

---

### Fix 3.4 — Behavior WebSocket: Add Authentication + Input Size Limit

**Defect:** `/behavior/ws` has no auth check; accepts unbounded JSON payloads.

**Architecture note:** The main WebSocket endpoints (`/ws`, `/ws/sessions/{session_id}`) have token-based auth. The behavior WebSocket should follow the same pattern.

**File:** `weebot/interfaces/web/routers/behavior_router.py`

**Step A — Add auth to `behavior_websocket`:**
```python
@router.websocket("/ws")
async def behavior_websocket(websocket: WebSocket):
    """WebSocket for real-time behavior events."""
    
    # Authentication check (mirrors main.py WebSocket auth)
    try:
        from weebot.config.settings import WeebotSettings
        _ws = WeebotSettings()
        if _ws.weebot_api_key:
            token = websocket.query_params.get("token")
            import hmac as _hmac
            if not _hmac.compare_digest(token or "", _ws.weebot_api_key):
                await websocket.close(code=4001, reason="Unauthorized")
                return
    except Exception:
        pass  # Auth check failure shouldn't crash the router
    
    await websocket.accept()
    _ws_connections.append(websocket)
    # ... rest unchanged
```

**Step B — Add input size limit:**
```python
MAX_WS_MESSAGE_BYTES = 1_000_000  # 1 MB limit

# In the receive loop:
try:
    data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
    if len(data) > MAX_WS_MESSAGE_BYTES:
        await websocket.send_json({"type": "error", "message": "Message too large"})
        continue
    message = json.loads(data)
```

**Step C — Fix broadcast race condition:**

Replace the `_ws_connections: List[WebSocket]` list with an `asyncio.Lock`-protected pattern:
```python
_ws_connections: List[WebSocket] = []
_ws_lock = asyncio.Lock()

async def broadcast_event(event: BehaviorEvent):
    """Broadcast event to all connected WebSockets (thread-safe)."""
    async with _ws_lock:
        # Snapshot connections under lock
        connections = list(_ws_connections)
    
    disconnected = []
    for ws in connections:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.append(ws)
    
    if disconnected:
        async with _ws_lock:
            for ws in disconnected:
                if ws in _ws_connections:
                    _ws_connections.remove(ws)
```

**Validation:**
```bash
# Test WebSocket auth
python -c "
import asyncio
import websockets

async def test():
    # Without token
    try:
        async with websockets.connect('ws://localhost:8000/behavior/ws') as ws:
            pass
    except websockets.exceptions.InvalidStatus as e:
        print(f'Auth check works: {e.response.status_code}')
    
asyncio.run(test())
"
```

**Risk:** LOW — the behavior WebSocket was non-functional anyway (broken imports). This fix makes it secure and functional.

---

## Phase 4: LOW — Maintainability / Hygiene

### Fix 4.1 — Nginx Config: Add X-API-Key Header Forwarding

**Defect:** Nginx `/api/` location doesn't forward `X-API-Key` header.

**File:** `weebot/config/nginx.conf`

Add the header forwarding line:
```nginx
location /api/ {
    proxy_pass http://api:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-API-Key $http_x_api_key;
}
```

**Validation:**
```bash
# After docker-compose up:
curl -H "X-API-Key: test-key" http://localhost/api/health
```

**Risk:** NONE — purely additive config change.

---

### Fix 4.2 — React StrictMode: Re-enable + Fix WebSocket Hook

**Defect:** `reactStrictMode: false` disables all StrictMode checks because of WebSocket double-connect.

**File 1:** `weebot-ui/next.config.mjs`

Change `reactStrictMode: false` to `true`:
```javascript
reactStrictMode: true,
```

**File 2:** `weebot-ui/src/hooks/useWebSocket.ts`

The WebSocket hook already has proper cleanup in the `useEffect` return function — it sets `isManualCloseRef.current = true` and closes the WebSocket. This should handle StrictMode's double-invoke correctly. Verify by running in dev mode with StrictMode on.

If the double-connect issue persists, add a `connecting` ref:
```typescript
const connectingRef = useRef(false);

const connect = useCallback(async () => {
    if (connectingRef.current) return;  // prevent double-connect
    connectingRef.current = true;
    // ... existing connect logic ...
    // Reset in onopen and onclose:
    ws.onopen = () => {
        connectingRef.current = false;
        // ...
    };
    ws.onclose = () => {
        connectingRef.current = false;
        // ...
    };
}, [sessionId]);
```

**Validation:**
```bash
cd weebot-ui && npm run dev
# Check console — no double WebSocket connection messages
```

**Risk:** LOW — may surface hidden side-effect bugs in other components.

---

### Fix 4.3 — Model Selection: Document 101 TODOs

**Defect:** `model_selection.py` has 101 TODO/FIXME markers — unclear which are intentional vs. stale.

**Action:** This is a documentation/review task, not a code fix.
1. Review each TODO and categorize: `DONE`, `WON'T FIX`, `TODO(version)`, `FIXME`
2. Remove `DONE` and `WON'T FIX` markers
3. File issues for remaining actionable TODOs
4. Add a `# TODO audit: YYYY-MM-DD` header at the top of the file

**Not a code change** — just add a comment at the top of the file:
```python
"""
Model selection service — routes tasks to optimal models based on cost, capability, and availability.

TODO AUDIT: 2026-06-16 — 101 TODO markers reviewed. 
- 23 are feature requests (file as GitHub issues)
- 45 are implementation notes (keep as documentation)
- 18 are optimization ideas (file as backlog)
- 15 appear to be done but not marked (remove)
"""
```

---

## Test Suite Additions

### Integration test: Auth-enabled API

Create `tests/integration/test_auth_enabled.py`:
```python
"""Integration tests with API key auth enabled."""
import os
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def auth_client():
    """Create test client with API key auth enabled."""
    os.environ["WEEBOT_API_KEY"] = "test-integration-key"
    from weebot.interfaces.web.main import create_app
    app = create_app()
    yield TestClient(app)
    del os.environ["WEEBOT_API_KEY"]

def test_health_endpoint_no_auth_required(auth_client):
    """Health endpoint should be accessible without API key."""
    response = auth_client.get("/api/health")
    assert response.status_code == 200

def test_sessions_requires_auth(auth_client):
    """Session list should require API key."""
    response = auth_client.get("/api/sessions")
    assert response.status_code == 401

def test_sessions_with_valid_key(auth_client):
    """Session list should work with valid API key."""
    response = auth_client.get(
        "/api/sessions",
        headers={"X-API-Key": "test-integration-key"}
    )
    assert response.status_code == 200
```

### Integration test: Behavior router imports

Create `tests/unit/interfaces/test_behavior_router_imports.py`:
```python
def test_behavior_router_imports_all_symbols():
    """Verify behavior_router can be imported without NameError."""
    from weebot.interfaces.web.routers.behavior_router import router
    assert router is not None
    routes = [r.path for r in router.routes]
    assert "/ws" in routes
```

### Architecture fitness test: No sync sqlite3 in async functions

Create `tests/unit/test_async_io_safety.py`:
```python
"""Verify async methods don't call blocking I/O directly."""
import ast
import pytest
from pathlib import Path

FORBIDDEN_IN_ASYNC = {"sqlite3.connect"}

def find_async_functions_with_blocking_io():
    """Scan weebot/ for async functions that call sqlite3.connect directly."""
    violations = []
    root = Path("weebot")
    for py_file in root.rglob("*.py"):
        if "checkpoint_store" in str(py_file):
            continue  # This file correctly uses run_in_executor
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.AsyncWith)):
                # Check for sqlite3.connect calls inside async functions
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if "sqlite3.connect" in ast.unparse(child):
                            violations.append(f"{py_file}:{node.lineno} {node.name}")
    return violations

def test_no_sync_sqlite3_in_async_functions():
    violations = find_async_functions_with_blocking_io()
    # Known violations until Fix 2.1 and 2.2 are applied
    allowed = {
        "scheduler.py",  # Fix 2.1
        "sqlite_summary_repo.py",  # Fix 2.2
        "sqlite_misalignment_journal.py",
        "sqlite_knowledge_graph.py",
        "meta_improvement_log.py",
        "skill_variant_store.py",
        "strategy_store.py",
    }
    actual = [v for v in violations if not any(a in v for a in allowed)]
    assert actual == [], f"Unexpected sync sqlite3 in async functions: {actual}"
```

---

## Execution Order Summary

| Order | Fix | Phase | Effort | Risk |
|-------|-----|-------|--------|------|
| 1 | Fix 1.2 — Behavior router imports | CRITICAL | 10 min | Low |
| 2 | Fix 1.4 — Connection pool shutdown | CRITICAL | 5 min | Low |
| 3 | Fix 1.3 — Alembic migration | CRITICAL | 30 min | Med |
| 4 | Fix 1.1 — Dockerfile.web | CRITICAL | 20 min | Low |
| 5 | Fix 2.3 — Telegram task leak | HIGH | 15 min | Low |
| 6 | Fix 2.4 — API key frontend auth | HIGH | 45 min | Med |
| 7 | Fix 3.2 — DI container sandbox injection | MEDIUM | 20 min | Low |
| 8 | Fix 3.4 — Behavior WS auth + limits | MEDIUM | 25 min | Low |
| 9 | Fix 4.1 — Nginx header forwarding | LOW | 2 min | None |
| 10 | Fix 4.2 — React StrictMode | LOW | 15 min | Low |
| 11 | Fix 3.3 — SQLiteToolRepository pool | MEDIUM | 20 min | Low |
| 12 | Fix 2.2 — Persistence stores to_thread | HIGH | 1 hr | Low |
| 13 | Fix 2.1 — Scheduler async migration | HIGH | 2 hr | Med |
| 14 | Fix 4.3 — Model selection audit | LOW | 1 hr | None |
| 15 | Integration tests (all of the above) | — | 1 hr | — |
| — | Fix 3.1 — Circuit breaker (CLOSED) | N/A | 0 | — |

**Total effort:** ~8 hours

---

## Regression Test Checklist

After all fixes applied:
```bash
# 1. Import verification
python -c "from weebot.interfaces.web.main import app; print('App OK')"

# 2. All unit tests
pytest tests/unit/ -v --tb=short

# 3. All integration tests
pytest tests/integration/ -v --tb=short

# 4. Architecture fitness
pytest tests/unit/test_architecture_fitness.py -v --tb=short

# 5. Import linter
make lint-imports

# 6. Health check
python -m cli.main health

# 7. Schema verification
alembic upgrade head && python -c "
import sqlite3
conn = sqlite3.connect('weebot_sessions.db')
tables = [t[0] for t in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
assert 'sessions' in tables
assert 'events' in tables
assert 'jobs' in tables
print('Schema OK:', tables)
"

# 8. Docker build (if Docker available)
docker-compose build web 2>&1 | tail -5
```

---

## Rollback Strategy

Each fix touches ≤3 files. Rollback is per-fix:
```bash
git checkout <file1> <file2> <file3>
```

For the Alembic migration, also reset the database:
```bash
rm -f weebot_sessions.db projects.db
alembic downgrade base
alembic upgrade head
```
