# Undiscovered Defects — Weebot Codebase

**Date:** 2026-06-16  
**Auditor Role:** Principal Architect / Security Auditor / SRE / Adversarial Reviewer  
**Scope:** Full forensic sweep beyond documented issues (01–08)  
**Method:** Direct code inspection with adversarial assumptions — assume hidden defects exist

---

## Overall Assessment

The previously audited critical issues (CORS, cache corruption, WebSocket auth bypass, HMAC typo) have been **fixed**. However, this sweep uncovered **17 new defects** the developers almost certainly do not know exist — spanning Docker build breakage, API endpoint failures, event-loop blocking, connection leaks, and authentication dead code paths. Several are **production-breaking**.

---

## 🔴 CRITICAL — Production-Breaking

### DEFECT-001: Docker Web Frontend Build is Broken

**File:** `Dockerfile.web:6`  
**Evidence:**
```dockerfile
FROM node:20-alpine AS build
...
RUN npm run build        # Next.js output goes to .next/

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html   # ← /app/dist DOES NOT EXIST
```

**Mechanism:** Next.js (`next build`) outputs compiled files to `.next/` directory by default. The Dockerfile copies from `/app/dist` — a path that never exists. The resulting nginx image will contain **no frontend files** (`/usr/share/nginx/html` will be empty). `docker-compose up` for the `web` service builds a blank web server.

**Impact:** Docker deployment is non-functional. Any team attempting to deploy via `docker-compose.yml` gets a blank nginx container.

**Fix:** Change to `COPY --from=build /app/.next /usr/share/nginx/html` and add a `next start` CMD, or add `output: 'standalone'` to `next.config.mjs` and use `COPY --from=build /app/.next/standalone` + `COPY --from=build /app/.next/static .next/static`.

---

### DEFECT-002: Behavior Router — 7 Endpoints Broken by Missing Imports

**File:** `weebot/interfaces/web/routers/behavior_router.py:1`  
**Evidence:** The file has exactly ONE import from the behavior module:
```python
from weebot.core.behavior_reporting import BehaviorReporter
```

But 7 endpoints use **unimported** classes/functions:

| Line | Endpoint | Missing Symbol | Defined In |
|------|----------|---------------|------------|
| 117 | `POST /behavior/override` | `TrustManager()` | `weebot/core/behavior_tracker.py:256` |
| 136,145 | `POST /behavior/watch/start` | `get_tracker()`, `create_tracker()` | `weebot/core/behavior_tracker.py:478,493` |
| 155,161 | `POST /behavior/watch/stop` | `get_tracker()`, `stop_tracker()` | `weebot/core/behavior_tracker.py:478,508` |
| 163 | `GET /behavior/watch/status` | `get_tracker()` | `weebot/core/behavior_tracker.py:478` |
| 176 | `POST /behavior/watch/start` (inner) | `BehaviorTracker` | `weebot/core/behavior_tracker.py` |
| 180 | `GET /behavior/self-knowledge` | `SelfKnowledgeGenerator()` | `weebot/core/behavior_reporting.py:328` |
| 188 | `POST /behavior/self-knowledge/regenerate` | `SelfKnowledgeGenerator()` | `weebot/core/behavior_reporting.py:328` |
| 215 | `broadcast_event()` | `BehaviorEvent` | `weebot/core/behavior_tracker.py` |
| 334 | `start_session_tracking()` | `create_tracker()` | `weebot/core/behavior_tracker.py:493` |
| 347 | `stop_session_tracking()` | `get_tracker()`, `stop_tracker()` | `weebot/core/behavior_tracker.py:478,508` |

**Mechanism:** Every call raises `NameError`. The global `@app.exception_handler(Exception)` in `main.py` catches it and returns HTTP 500 with `{"error_code": "INTERNAL_ERROR", "detail": "An internal error occurred"}`. Callers get a generic 500 — no stack trace, no indication of which symbol is missing.

**Impact:** The entire behavior tracking API surface is dead code. Trust score overrides, self-knowledge generation, file-watching start/stop — all fail silently. This has likely been broken since the behavior router was written; the missing imports went unnoticed because behavior tracking is an auxiliary feature with no integration/E2E tests.

**Fix:** Add to imports:
```python
from weebot.core.behavior_tracker import (
    TrustManager, BehaviorTracker, BehaviorEvent,
    create_tracker, get_tracker, stop_tracker,
)
from weebot.core.behavior_reporting import SelfKnowledgeGenerator
```

---

### DEFECT-003: Alembic Migration is Empty — No Schema Actually Migrated

**File:** `alembic/versions/548511c41c39_initial_schema.py:21-25`  
**Evidence:**
```python
def upgrade() -> None:
    """Upgrade schema."""
    pass

def downgrade() -> None:
    """Downgrade schema."""
    pass
```

**Mechanism:** The migration file was generated but never populated. Alembic's `command.upgrade(alembic_cfg, "head")` runs in `main.py:155` on every startup and succeeds — but does **nothing**. All actual schema creation happens via ad-hoc `CREATE TABLE IF NOT EXISTS` scattered across:
- `event_store.py:124-145` (`sessions`, `events` tables)
- `scheduler.py:111-127` (`jobs` table)
- `sqlite_state_repo.py` (implicit)

**Impact:** 
1. Alembic version tracking exists but is useless — it records a migration that did nothing
2. No rollback capability — `command.downgrade()` is also `pass`
3. Schema changes cannot be versioned or replayed
4. Multiple subsystems independently create tables with no coordination

**Fix:** Either populate the migration with actual DDL, or remove Alembic and document that schema is managed via `CREATE TABLE IF NOT EXISTS`.

---

### DEFECT-004: Connection Pool Never Closed on Shutdown

**File:** `weebot/infrastructure/persistence/connection_pool.py:370`  
**Evidence:** `close_all_pools()` is defined and exported via `__init__.py:7`, but **never called** in `web/main.py`'s lifespan shutdown block. The shutdown block (lines 171-182) persists circuit breaker state, stops the scheduler, and logs — but does not close connection pools.

**Impact:** On every `uvicorn` restart, all aiosqlite connections in the pool registry leak. Each restart leaves `max_read_connections + 1` (write) open file handles. Over repeated restarts (development, auto-reload), this exhausts file descriptors.

**Fix:** Add to the lifespan shutdown block:
```python
from weebot.infrastructure.persistence.connection_pool import close_all_pools
await close_all_pools()
```

---

## 🟠 HIGH — Functional / Security / Architecture

### DEFECT-005: Scheduler Uses Synchronous `sqlite3` in Async Methods — Blocks Event Loop

**File:** `weebot/scheduling/scheduler.py:111,247,257,438`  
**Evidence:** Every database operation uses blocking `sqlite3.connect()`:
```python
# scheduler.py:111 — _init_db()
with sqlite3.connect(self.db_path) as conn:     # ← sync, blocks event loop
    conn.execute('CREATE TABLE IF NOT EXISTS jobs ...')

# scheduler.py:247 — delete_job()
with sqlite3.connect(self.db_path) as conn:     # ← sync, blocks event loop
    conn.execute('DELETE FROM jobs ...')

# scheduler.py:257 — get_job()  
with sqlite3.connect(self.db_path) as conn:     # ← sync, blocks event loop
    ...

# scheduler.py:438 — _save_job()
with sqlite3.connect(self.db_path) as conn:     # ← sync, blocks event loop
    conn.execute(f'INSERT OR REPLACE INTO jobs ...')
```

These are called from **async methods**: `create_job()`, `update_job()`, `delete_job()`, `get_job()`, `_execute_job()`, `start()`, `stop()`. Each call blocks the asyncio event loop for the duration of disk I/O (typically 1-20ms for SQLite, but spikes to 100ms+ under WAL checkpoint pressure).

**Impact:** Under load (multiple concurrent scheduled jobs), the event loop stalls, delaying all other async operations (WebSocket messages, HTTP responses, health checks). This is a systemic issue — the `AsyncIOScheduler` is async, but its persistence layer is sync.

**Fix:** Switch to `aiosqlite` or wrap with `asyncio.to_thread()`:
```python
async def _get_conn(self):
    return await aiosqlite.connect(self.db_path)
```

---

### DEFECT-006: Multiple Persistence Stores Block Event Loop with Sync SQLite

Same pattern as DEFECT-005, affecting these additional files:

| File | Sync `sqlite3.connect()` lines |
|------|-------------------------------|
| `sqlite_summary_repo.py` | 20, 38, 50 |
| `sqlite_misalignment_journal.py` | 54, 60 |
| `sqlite_knowledge_graph.py` | 55 |
| `meta_improvement_log.py` | 60, 79, 105 |
| `skill_variant_store.py` | 53, 62, 86, 101, 115, 126, 145 |
| `strategy_store.py` | 48, 56, 87, 114, 128 |

All are called from async methods without `asyncio.to_thread()`.

**Contrast:** `checkpoint_store.py` correctly uses `loop.run_in_executor(None, ...)` for every sync SQLite call — the only correct implementation.

---

### DEFECT-007: Telegram Adapter Creates Unstoppable Background Task

**File:** `weebot/interfaces/gateways/telegram.py:49`  
**Evidence:**
```python
async def start(self) -> None:
    self._running = True
    asyncio.create_task(self._poll_loop())  # ← NO REFERENCE STORED
    logger.info("TelegramAdapter started")

async def stop(self) -> None:
    self._running = False  # ← only sets flag, can't cancel the task
    logger.info("TelegramAdapter stopped")
```

**Mechanism:** The `asyncio.create_task()` return value is discarded. `stop()` sets a boolean flag but has no handle to cancel the task. If the task is blocked on a network I/O call (`aiohttp` request with 30s timeout), it continues running for up to 30s after `stop()` returns. On event loop shutdown, this produces: `Task was destroyed but it is pending!`

**Impact:** Resource leak on adapter stop. During clean shutdown, the orphan task may attempt database writes after the connection pool closes, causing cascading errors.

**Fix:**
```python
async def start(self) -> None:
    self._running = True
    self._poll_task = asyncio.create_task(self._poll_loop())

async def stop(self) -> None:
    self._running = False
    if self._poll_task:
        self._poll_task.cancel()
        try:
            await self._poll_task
        except asyncio.CancelledError:
            pass
```

---

### DEFECT-008: API Key Proxy Chain is Broken (Client → Next.js → Backend)

**Files:** `weebot-ui/src/lib/api.ts`, `weebot-ui/src/app/api/[[...path]]/route.ts:20-22`

**Evidence:**

**Client side** (`lib/api.ts`): The `fetchApi()` function sends requests to `/api/...` through the Next.js proxy. It never includes an `X-API-Key` header. Therefore the client never authenticates.

**Proxy side** (`route.ts:20-22`):
```typescript
const apiKey = request.headers.get("x-api-key");  // reads from client request
if (apiKey) {
    proxyHeaders["X-API-Key"] = apiKey;  // forwards to backend
}
```

Since the client never sends `x-api-key`, the proxy never forwards one. When `WEEBOT_API_KEY` is set on the backend, **all proxied requests receive HTTP 401**.

Additionally, there's no UI for the user to enter/provide an API key. The frontend has no concept of authentication.

**Impact:** When `WEEBOT_API_KEY` is configured for production security, the web UI becomes unusable — every API call through the Next.js proxy returns 401. This creates a perverse incentive to leave the API key unset, defeating the security hardening applied in the earlier fixes.

---

### DEFECT-009: WebSocket Token Resolution is Dead Code

**File:** `weebot-ui/src/hooks/useWebSocket.ts:21-30`  
**Evidence:**
```typescript
async function _resolveWsToken(): Promise<string | null> {
    const res = await fetch("/api/health");
    if (!res.ok) return null;
    const data = await res.json();
    _cachedWsToken = data.ws_token || null;  // ← health endpoint never returns ws_token
    return _cachedWsToken;
}
```

The backend `/api/health` endpoint does not return a `ws_token` field. The WebSocket auth was fixed in the backend (middleware no longer skips `/ws` paths), but the frontend has no way to obtain a valid token. WebSocket connections always fail with 401 when `WEEBOT_API_KEY` is set.

**Impact:** Real-time event streaming is broken in the web UI when API key auth is enabled.

---

## 🟡 MEDIUM — Architecture / Reliability / Performance

### DEFECT-010: Circuit Breaker `get_state()` Reads Without Lock

**File:** `weebot/core/circuit_breaker.py:237-239`  
**Evidence:**
```python
def get_state(self, entity_id: str) -> BreakerState:
    """Get the current state for *entity_id* (sync, for inspection)."""
    entry = self._breakers.get(entity_id)       # ← no lock
    return entry.state if entry else BreakerState.CLOSED
```

While `record_success()`, `record_failure()`, and `reset()` all mutate `_breakers` under `self._lock`, `get_state()` reads without acquiring it. A concurrent `record_failure()` that transitions to OPEN and replaces the `_BreakerEntry` could race with `get_state()`, producing a stale CLOSED reading.

**Reachability:** `get_state()` is called from `evaluate()`'s Phase 1 dirty-check (line 84) without the lock, and from monitoring/API paths. The dirty-check is intentionally lock-free, but the monitoring paths should be accurate.

---

### DEFECT-011: DI Container Creates Tools Without Sandbox Injection

**File:** `weebot/application/di/__init__.py:168-178` (`build_mediator`)  
**Evidence:**
```python
tools = ToolCollection(BashTool(), FileEditorTool(), PythonTool(), ImageGenTool())
```

These tools are instantiated with **no constructor arguments**. `PythonExecuteTool` requires a `SandboxPort` to execute code; `BashTool` has a fallback that creates its own DI container (a known anti-pattern from the previous audit). The `_create_sub_agent_factory` (line 229) does the same thing.

**Impact:** Python tool execution in the mediator codepath will either fail or create orphan DI containers. This is the same class of issue identified in `tasks/pre-existing-issues-fix-plan.md` Issue #2.

---

### DEFECT-012: SQLiteToolRepository Opens New Connection Per Query

**File:** `weebot/infrastructure/persistence/sqlite_tool_repo.py`  
**Evidence:** Every method pattern:
```python
async def get_tool(self, name: str):
    conn = await aiosqlite.connect(self.db_path)
    try:
        ...
    finally:
        await conn.close()
```

This creates connection overhead (file open + WAL setup + close) on every query instead of using the shared connection pool. For a session with 20+ tool calls, this is 20+ unnecessary connection cycles.

---

### DEFECT-013: React StrictMode Disabled — Hides Side-Effect Bugs

**File:** `weebot-ui/next.config.mjs:14`  
**Evidence:**
```javascript
reactStrictMode: false,
```

The comment says "Disable strict mode for WebSocket connections in dev" but this disables ALL StrictMode checks. React StrictMode double-invokes render functions, effects, and state updaters in development to surface side-effect bugs. Disabling it hides these bugs rather than fixing the underlying WebSocket issue.

---

### DEFECT-014: WebSocket Accepts Unbounded JSON Payloads

**File:** `weebot/interfaces/web/routers/behavior_router.py:256-258`  
**Evidence:**
```python
data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
message = json.loads(data)   # ← no size limit
```

A malicious client could send a multi-gigabyte JSON payload that `json.loads()` parses entirely in memory, causing OOM. No `max_size` parameter or content-length check exists.

---

### DEFECT-015: Behavior Router WebSocket Broadcast Has Race on Disconnect List

**File:** `weebot/interfaces/web/routers/behavior_router.py:228-240`  
**Evidence:** `broadcast_event()` iterates `_ws_connections` and collects disconnected websockets into a `disconnected` list, then removes them. But `_ws_connections` is also modified by the WebSocket handler's `finally` block. Two concurrent broadcasts (or a broadcast + disconnect) can produce a `ValueError: list.remove(x): x not in list`.

---

## 🔵 LOW — Maintainability / Hygiene

### DEFECT-016: Nginx Config Missing API Key Header Forwarding

**File:** `weebot/config/nginx.conf`  
**Evidence:** The `/api/` location block proxies to the backend but does not forward `X-API-Key`:
```nginx
location /api/ {
    proxy_pass http://api:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    # Missing: proxy_set_header X-API-Key $http_x_api_key;
}
```

When the Next.js proxy is bypassed (e.g., direct nginx → backend via Docker Compose), API key authentication cannot work because nginx strips custom headers by default.

---

### DEFECT-017: `model_selection.py` — 101 TODO Markers

**File:** `weebot/application/services/model_selection.py`  
**Evidence:** Search shows 101 TODO/FIXME markers in this single file. This is the highest concentration in the codebase and indicates either rapid iteration without cleanup, or a component that was never completed. The file manages model routing decisions — a correctness-critical function — yet has unresolved design questions scattered throughout.

---

## Defect Matrix

| ID | Severity | Category | Reachable in Prod? | Fix Effort |
|----|----------|----------|--------------------|------------|
| DEFECT-001 | 🔴 CRITICAL | Docker build broken | Yes — `docker-compose up` | 15 min |
| DEFECT-002 | 🔴 CRITICAL | API endpoints broken | Yes — all behavior routes return 500 | 10 min |
| DEFECT-003 | 🔴 CRITICAL | Migration system broken | Yes — every startup | 30 min |
| DEFECT-004 | 🔴 CRITICAL | Connection leak | Yes — every uvicorn restart | 5 min |
| DEFECT-005 | 🟠 HIGH | Event loop blocking | Yes — every scheduled job | 2 hrs |
| DEFECT-006 | 🟠 HIGH | Event loop blocking | Yes — session operations | 3 hrs |
| DEFECT-007 | 🟠 HIGH | Resource leak | When Telegram adapter used | 15 min |
| DEFECT-008 | 🟠 HIGH | Auth chain broken | When WEEBOT_API_KEY set | 45 min |
| DEFECT-009 | 🟠 HIGH | WebSocket auth broken | When WEEBOT_API_KEY set | 20 min |
| DEFECT-010 | 🟡 MEDIUM | Race condition | Monitoring/multi-entity | 10 min |
| DEFECT-011 | 🟡 MEDIUM | DI wiring | Mediator + sub-agent paths | 1 hr |
| DEFECT-012 | 🟡 MEDIUM | Performance | Every tool DB lookup | 30 min |
| DEFECT-013 | 🟡 MEDIUM | Dev tooling | Development only | 1 hr |
| DEFECT-014 | 🟡 MEDIUM | DoS surface | When behavior WS used | 15 min |
| DEFECT-015 | 🟡 MEDIUM | Race on disconnect | Concurrent broadcasts | 20 min |
| DEFECT-016 | 🔵 LOW | Config gap | Docker Compose deployment | 5 min |
| DEFECT-017 | 🔵 LOW | Tech debt | N/A | Ongoing |

---

## Previously Documented Issues — Status Verification

| Original Finding | Status |
|-----------------|--------|
| Module-level variable corruption (resilient_adapter.py) | ✅ FIXED — stray lines removed |
| CORS wildcard with credentials | ✅ FIXED — explicit origin list |
| WebSocket endpoints bypass auth | ✅ FIXED — skip removed, timing-safe compare |
| HMAC typo (`hmac.new` → `hmac.HMAC`) | ✅ FIXED |
| Session list memory load | ✅ FIXED — SQL-level pagination |
| Self-instantiated containers in tools | ⚠️ PARTIAL — still happens in `build_mediator` |

---

## Test Gaps Discovered

1. **No tests for behavior_router.py** — 7 broken endpoints with zero test coverage would have caught DEFECT-002 immediately
2. **No E2E test for Docker Compose** — DEFECT-001 would be caught by `docker-compose up --build && curl localhost`
3. **No test for API key + WebSocket** — DEFECT-008/009 would be caught by an authenticated integration test
4. **No async-blocking detection** — DEFECT-005/006 require `pytest-asyncio` with `--blocking-threshold` or debug mode warnings
5. **No integration tests for Telegram adapter** — DEFECT-007 would be caught by start/stop lifecycle test
6. **No fuzz tests for WebSocket endpoints** — DEFECT-014 would be caught by sending large JSON payloads
7. **No contract test for health endpoint schema** — DEFECT-009 would be caught by asserting response shape
