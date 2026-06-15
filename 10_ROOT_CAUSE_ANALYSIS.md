# Root Cause Analysis — Weebot 17 Undiscovered Defects

**Date:** 2026-06-16  
**Method:** Defect → proximate cause → originating commit → systemic cause  
**Scope:** Full chain of causation for all 17 defects

---

## Methodology

Each defect is traced through four layers:
1. **Proximate cause** — the immediate code-level error
2. **Originating commit** — when it was introduced and by what decision
3. **Detection failure** — why it wasn't caught before reaching `main`
4. **Systemic root cause** — the process/architectural pattern that allowed it

---

## Defect Root Cause Chains

### DEFECT-001 — Docker Web Frontend Build Broken

| Layer | Finding |
|-------|---------|
| **Proximate** | `Dockerfile.web:6` copies from `/app/dist`; Next.js outputs to `.next/` |
| **Originating commit** | `bb858d9` — "Enhancement 9 — Docker Deployment" (Jun 3, 2026) |
| **What happened** | Docker support was added as a standalone enhancement in a single commit. The author wrote a multi-stage Dockerfile following a generic Node/nginx pattern but used `/app/dist` — the output path for CRA/Vite — instead of Next.js's `.next/` convention. |
| **Detection failure** | No CI step runs `docker-compose up --build` or validates the Docker image. No E2E test hits the web service after build. |
| **Systemic cause** | **Enhancement checklist anti-pattern** — features are added to say they exist (for completeness) without integration verification. Docker was "done" when files were committed, not when it actually deployed. |

---

### DEFECT-002 — Behavior Router: 7 Endpoints Broken by Missing Imports

| Layer | Finding |
|-------|---------|
| **Proximate** | `behavior_router.py` imports only `BehaviorReporter` but uses `TrustManager`, `SelfKnowledgeGenerator`, `create_tracker`, `get_tracker`, `stop_tracker`, `BehaviorEvent`, `BehaviorTracker` — all undefined |
| **Originating commit** | `22cfb73` — "clean-architecture refactor and project restructure" (May 31, 2026) |
| **What happened** | A single massive commit simultaneously created `behavior_tracker.py` (49 KB, 18 classes), `behavior_reporting.py` (17 KB, classes + reporting), and `behavior_router.py` (14 KB, 13 endpoints). The router was written against classes split between two new files. Only the `BehaviorReporter` import was added; the 7+ other symbol imports were overlooked. |
| **Detection failure** | 1. No unit or integration test for any behavior router endpoint. 2. The global `@app.exception_handler(Exception)` in `main.py:146` catches `NameError` and returns generic HTTP 500, hiding the actual error from anyone testing manually. 3. Behavior tracking is an auxiliary feature — nobody exercises it during development. |
| **Systemic cause** | **Big-bang refactor without automated cross-reference verification.** The importlinter config only checks architecture-layer boundaries (domain can't import infrastructure), not intra-layer import correctness. No lint rule detects use of undefined symbols in Python (this requires runtime or a type checker like mypy/pyright, which are not in CI). |

---

### DEFECT-003 — Alembic Migration Empty

| Layer | Finding |
|-------|---------|
| **Proximate** | `alembic/versions/548511c41c39_initial_schema.py` — both `upgrade()` and `downgrade()` are `pass` |
| **Originating commit** | `851bc0a` — "refactor(phase4): async EventStore, Alembic migrations, circuit breaker persistence, PlanActFlow decomposition" |
| **What happened** | Alembic was scaffolded (`alembic revision --autogenerate`) against a database that already had tables created by ad-hoc `CREATE TABLE IF NOT EXISTS` statements in `event_store.py` and `scheduler.py`. The autogenerate detected no differences (tables already exist) and produced an empty migration. Rather than reconciling — either by dropping ad-hoc creation and populating the migration, or by dropping Alembic — the empty file was committed. |
| **Detection failure** | The `command.upgrade()` call in `main.py:155` succeeds (it runs `pass`). The health check only verifies the API responds, not that schema is versioned. |
| **Systemic cause** | **Half-migration anti-pattern** — a migration system was added to an existing codebase with competing schema creation mechanisms. The two systems were never reconciled because both "work" independently. This is a common failure when adding migrations retroactively. |

---

### DEFECT-004 — Connection Pool Never Closed on Shutdown

| Layer | Finding |
|-------|---------|
| **Proximate** | `close_all_pools()` is defined and exported but never called in `web/main.py` lifespan shutdown |
| **Originating commits** | `22cfb73` — connection_pool.py created; lifespan added later, iterated across 14+ commits |
| **What happened** | The connection pool was created in the initial refactor. The `close_all_pools()` utility was added later. The FastAPI lifespan shutdown block evolved across 14+ commits for different concerns (circuit breaker persistence, scheduler stop, heartbeat stop). The pool cleanup was simply never added to the growing shutdown checklist. |
| **Detection failure** | No test for clean shutdown. No monitoring of open file descriptors. The leak is invisible in development (few restarts) and only manifests in production over time. |
| **Systemic cause** | **Accretion-driven development** — the shutdown block grew incrementally as each subsystem was added, but no "shutdown completeness" test or checklist exists. Each developer added their own cleanup but didn't audit the full shutdown surface. |

---

### DEFECT-005 — Scheduler Blocks Event Loop with Sync SQLite

| Layer | Finding |
|-------|---------|
| **Proximate** | `scheduler.py` uses `sqlite3.connect()` directly in `_init_db()`, `delete_job()`, `get_job()`, `_save_job()` — all called from async methods |
| **Originating commit** | `3029ba8` — "Phase 3 - Add scheduling with APScheduler" |
| **What happened** | The scheduler was built in "Phase 3" using the standard library `sqlite3` module — the natural choice for a Python developer writing a persistence layer. The async connection pool (`aiosqlite`) was introduced later but the scheduler was never migrated. The `importlinter` config explicitly allows this: `weebot.scheduling.scheduler -> sqlite3` is in the ignore list. |
| **Detection failure** | No CI step detects blocking I/O in async functions. Python does not warn about this at runtime. Symptoms (event loop lag) are invisible until load testing. |
| **Systemic cause** | **Phase-async-mismatch** — components built in earlier phases used synchronous patterns. Later phases introduced async infrastructure but earlier components were never retrofitted. The importlinter exception for `scheduler -> sqlite3` codified this as acceptable. |

---

### DEFECT-006 — Multiple Persistence Stores Block Event Loop

| Layer | Finding |
|-------|---------|
| **Proximate** | 6 files use sync `sqlite3.connect()` in async methods: `sqlite_summary_repo.py`, `sqlite_misalignment_journal.py`, `sqlite_knowledge_graph.py`, `meta_improvement_log.py`, `skill_variant_store.py`, `strategy_store.py` |
| **Originating commits** | Various — most created during the `22cfb73` refactor or in subsequent "Phase" commits |
| **What happened** | The `checkpoint_store.py` demonstrates the correct pattern (`loop.run_in_executor(None, ...)`). But this pattern was never documented as a standard, never enforced by linting, and never checked in code review. Each developer chose their own approach — some used `aiosqlite`, some used `asyncio.to_thread`, some used raw `sqlite3`. |
| **Detection failure** | No architectural fitness test verifies that async methods don't call blocking I/O. No `pytest-asyncio` configuration with `--blocking-threshold` warnings. |
| **Systemic cause** | **Missing async I/O standard** — the codebase has three different async SQLite patterns (aiosqlite pool, `run_in_executor`, raw `sqlite3`) with no enforcement mechanism. This is architectural drift from a codebase that evolved from sync to async without a clear migration plan. |

---

### DEFECT-007 — Telegram Adapter Unstoppable Background Task

| Layer | Finding |
|-------|---------|
| **Proximate** | `telegram.py:49` — `asyncio.create_task(self._poll_loop())` return value discarded; `stop()` only sets boolean flag |
| **Originating commit** | `1d1627c` — "gateway SOUL.md profile support" or `a0a7cb2` — "Hermes-inspired enhancements" |
| **What happened** | This is the classic Python asyncio `create_task` anti-pattern — creating a fire-and-forget task without storing a reference. It's the most common asyncio bug in Python codebases. The developer likely assumed `stop()` → `self._running = False` would cause the loop to exit on the next iteration, which is correct in the happy path, but doesn't handle the case where the task is blocked on I/O. |
| **Detection failure** | No lifecycle test for Telegram adapter. No `pytest-asyncio` warning about unawaited tasks. Python only warns about this at event loop shutdown. |
| **Systemic cause** | **No async lifecycle test standard** — adapters with `start()`/`stop()` methods have no common test for "start, wait, stop, verify clean shutdown." Each adapter is tested independently or not at all. |

---

### DEFECT-008 — API Key Proxy Chain Broken

| Layer | Finding |
|-------|---------|
| **Proximate** | Client (`lib/api.ts`) never sends `X-API-Key`; proxy (`route.ts`) reads `x-api-key` (empty); backend requires `X-API-Key` |
| **Originating commits** | Backend hardening: `4b4c96f` — "fix(security): audit remediation — CORS, WS auth, HMAC, cache corruption, pagination". Frontend: various commits, never updated. |
| **What happened** | The security audit (documents 01-08) identified missing API key auth as critical. The backend was hardened: middleware now requires `X-API-Key` with timing-safe comparison. But the frontend was never updated — it has no auth UI, no API key input, no header injection. The Next.js proxy reads a header the client never sends. |
| **Detection failure** | No integration test runs the backend with `WEEBOT_API_KEY` set and the frontend making requests. All testing was backend-only with the API key disabled. |
| **Systemic cause** | **Security hardening without cross-layer integration testing** — backend security was treated as a backend-only concern. The frontend was assumed to "just work" because nobody tested with `WEEBOT_API_KEY` enabled. |

---

### DEFECT-009 — WebSocket Token Resolution Dead Code

| Layer | Finding |
|-------|---------|
| **Proximate** | `useWebSocket.ts:28` reads `data.ws_token` from `/api/health` response; the health endpoint never returns this field |
| **Originating commit** | Unknown — the `useWebSocket.ts` was written with the assumption that `/api/health` would return a WebSocket token, but the backend health endpoint was never updated to provide one. |
| **What happened** | The WebSocket auth fix (removing the `/ws` skip from middleware) was applied to the backend. The frontend developer anticipated this by writing token resolution logic, but the backend developer never implemented the token issuance endpoint. Two developers (or the same developer at different times) worked on opposite sides of the same feature without coordination. |
| **Detection failure** | No contract test for the health endpoint schema. No test that verifies WebSocket connection succeeds with auth enabled. |
| **Systemic cause** | **Split-brain feature development** — the frontend and backend were developed with different assumptions about the API contract. No OpenAPI spec or contract test enforced the agreement. |

---

### DEFECT-010 — Circuit Breaker `get_state()` Reads Without Lock

| Layer | Finding |
|-------|---------|
| **Proximate** | `circuit_breaker.py:237-239` — `self._breakers.get(entity_id)` without acquiring `self._lock` |
| **Originating commit** | `22cfb73` — created in the big-bang refactor |
| **What happened** | The `get_state()` method was written as a "convenience inspector" — sync, for monitoring dashboards. The developer assumed reads are safe without a lock in Python (dict reads are atomic at the C level). But the values are `_BreakerEntry` dataclass instances — replacing an entry under the lock while `get_state()` reads it can produce a torn read of the dataclass fields. |
| **Detection failure** | No concurrency test for the circuit breaker. Race conditions are inherently non-deterministic. |
| **Systemic cause** | **Lock discipline not enforced** — the `asyncio.Lock` is used in mutation methods but no consistent pattern (e.g., context manager, decorator) ensures all access paths acquire it. This is a design-level gap: the class doesn't enforce its own locking invariant. |

---

### DEFECT-011 — DI Container Creates Tools Without Sandbox

| Layer | Finding |
|-------|---------|
| **Proximate** | `di/__init__.py:168-178` and `:229` — `BashTool()`, `PythonExecuteTool()` created with no constructor arguments |
| **Originating commits** | `22cfb73` — DI container created; tools created inline without dependency resolution |
| **What happened** | The `build_mediator()` and `_create_sub_agent_factory()` methods were written as convenience builders that create a "standard tool set." But the tools need infrastructure dependencies (SandboxPort for PythonExecuteTool). The tools have fallback logic that creates their own DI containers, but this was flagged as an anti-pattern in the previous audit. The fix was applied to the main code paths but these convenience methods were missed. |
| **Detection failure** | No test exercises `build_mediator()` with Python tool execution. |
| **Systemic cause** | **Incomplete remediation** — the previous audit's fix (removing self-instantiated containers from tools) was applied to the primary code paths but not exhaustively verified across all call sites. |

---

### DEFECT-012 — SQLiteToolRepository Opens New Connection Per Query

| Layer | Finding |
|-------|---------|
| **Proximate** | Every method opens `aiosqlite.connect()` and closes in `finally` — no connection reuse |
| **Originating commit** | `22cfb73` — the tool repo was created alongside the connection pool |
| **What happened** | The `SQLiteConnectionPool` was created in the same refactor, but the `SQLiteToolRepository` was written independently (or by a different developer, or at a different time in the same large commit) and never migrated to use the pool. |
| **Detection failure** | No performance test or connection-count metric exposes this. |
| **Systemic cause** | **Parallel implementation without convergence** — two solutions for the same problem (async SQLite access) were created simultaneously but never unified. |

---

### DEFECT-013 — React StrictMode Disabled

| Layer | Finding |
|-------|---------|
| **Proximate** | `next.config.mjs:12` — `reactStrictMode: false` |
| **Originating commit** | Unknown — likely the initial frontend setup |
| **What happened** | WebSocket connections in React StrictMode cause double-connection during development (StrictMode double-invokes effects). Instead of fixing the `useWebSocket` hook to handle cleanup properly, StrictMode was disabled entirely — trading away all StrictMode checks (double-render detection, effect cleanup verification) for a WebSocket convenience. |
| **Detection failure** | The comment says "Disable strict mode for WebSocket connections in dev" — the developer knew it was a workaround. |
| **Systemic cause** | **Workaround-as-fix anti-pattern** — a development inconvenience was fixed by disabling a safety mechanism rather than addressing the root cause in the WebSocket hook. |

---

### DEFECT-014 — WebSocket Accepts Unbounded JSON

| Layer | Finding |
|-------|---------|
| **Proximate** | `behavior_router.py:256-258` — `json.loads(data)` with no size limit |
| **Originating commit** | `22cfb73` — behavior router created |
| **What happened** | This is a standard WebSocket implementation oversight. `websocket.receive_text()` returns the full message, and `json.loads()` parses it without a size check. Most developers don't think about malicious clients sending 1 GB JSON payloads. |
| **Detection failure** | No fuzz testing for WebSocket endpoints. |
| **Systemic cause** | **No input validation standard for WebSocket handlers** — HTTP endpoints have FastAPI's automatic validation via Pydantic models; WebSocket handlers have no equivalent. |

---

### DEFECT-015 — Behavior WebSocket Broadcast Race on Disconnect

| Layer | Finding |
|-------|---------|
| **Proximate** | `behavior_router.py:228-240` — `broadcast_event()` iterates `_ws_connections` and removes from it, but the WebSocket handler's `finally` block also removes |
| **Originating commit** | `22cfb73` |
| **What happened** | Shared mutable list with concurrent modification from two paths. Classic asyncio concurrency bug — both the broadcast loop and the disconnect handler modify the same list without coordination. |
| **Detection failure** | No concurrency test with multiple WebSocket clients. |
| **Systemic cause** | **Shared mutable state without synchronization** — the `_ws_connections` list is a module-level global modified by multiple coroutines. No lock, no `asyncio.Queue`, no immutable snapshot pattern. |

---

## Systemic Root Causes — The 6 Patterns

### 1. Big-Bang Refactor Without Verification (Affects: 002, 005, 006, 010, 012, 015)

The entire codebase was restructured from a monolithic layout to Clean Architecture in a single commit (`22cfb73`). This created 60+ files and touched every import in the project. The scale of the change made it impossible to manually verify every cross-reference. Importlinter was configured but only checks architectural layer boundaries — it cannot detect that `behavior_router.py` uses symbols from `behavior_tracker.py` without importing them. A language with compile-time checks (TypeScript, Rust, Go) would catch this; Python requires runtime or a type checker (mypy/pyright).

**Evidence:** 6 of 17 defects trace to this single commit or the "Phase" commits that followed the same pattern.

---

### 2. Enhancement Checklist Anti-Pattern (Affects: 001, 003, 004, 005, 006)

Features are added to satisfy a completeness checklist rather than to solve a verified need. Docker was added as "Enhancement 9" — the naming implies a numbered list of features to tick off. Alembic was scaffolded as "Phase 4" without populating the migration. Each enhancement was committed when the files existed, not when the feature was verified. The pattern: **commit → move on → never revisit**.

**Evidence:** Dockerfile.web has never produced a working image. The Alembic migration has been empty since creation. The scheduler has used sync sqlite3 since Phase 3.

---

### 3. Cross-Layer Integration Gap (Affects: 004, 008, 009)

The backend and frontend are developed as independent projects sharing a repo. Backend security hardening was applied without frontend updates. Connection pool cleanup was implemented without wiring it into the shutdown lifecycle. The two halves of the WebSocket auth feature (token issuance, token consumption) were implemented on opposite sides of the HTTP boundary with no shared contract.

**Evidence:** 3 of 4 CRITICAL defects involve cross-layer integration failures. Not one involves a logic error within a single layer.

---

### 4. Missing Async I/O Standard (Affects: 005, 006, 007)

The codebase has three competing async SQLite patterns and no enforcement of which to use. The correct pattern (`run_in_executor` in checkpoint_store.py) exists but was never promoted to a standard. The `asyncio.create_task` fire-and-forget anti-pattern appears in the Telegram adapter because there's no lifecycle test that catches it.

**Evidence:** 7 files block the event loop with sync I/O in async functions. Only 1 file does it correctly.

---

### 5. No Integration/E2E Test Coverage (Affects: ALL)

The CI pipeline runs unit tests, architecture fitness tests, and importlinter — but no integration tests with auth enabled, no E2E tests of the web UI, no Docker build verification, and no behavior router tests. Defects 001–009 would all have been caught by even basic integration tests:
- A test that starts the backend with `WEEBOT_API_KEY=test` and makes an API call would catch DEFECT-008
- A test that calls `POST /behavior/override` would catch DEFECT-002
- A test that runs `docker-compose up --build` would catch DEFECT-001

---

### 6. Silent Error Masking (Affects: 002)

The global exception handler in `main.py:146` catches all exceptions and returns a generic HTTP 500. This is correct for production but hides `NameError`, `ImportError`, and other development-time errors that would immediately point to the problem during manual testing. A developer calling a broken endpoint sees `{"error_code": "INTERNAL_ERROR", "detail": "An internal error occurred"}` instead of `NameError: name 'TrustManager' is not defined`.

---

## Prevention Recommendations

| Root Cause | Prevention |
|------------|-----------|
| Big-bang refactor | Incremental refactors with passing tests at each step; mypy/pyright in CI to catch undefined symbols |
| Enhancement checklist | Definition of done must include integration verification, not just file existence |
| Cross-layer integration gap | Contract tests (OpenAPI schema validation; verify frontend works with auth enabled) |
| Missing async standard | Architectural fitness test that detects sync I/O in async functions; lint rule |
| No integration/E2E tests | Add integration test suite running with `WEEBOT_API_KEY` set; add Docker build verification to CI |
| Silent error masking | In development mode, return full traceback in error responses; only use generic messages in production |

---

## Defect-to-Root-Cause Mapping

```
DEFECT-001 ──→ Enhancement checklist (no integration test)
DEFECT-002 ──→ Big-bang refactor + silent error masking + no tests
DEFECT-003 ──→ Enhancement checklist (half-migration)
DEFECT-004 ──→ Accretion-driven development (cross-layer gap)
DEFECT-005 ──→ Missing async standard + enhancement checklist
DEFECT-006 ──→ Missing async standard + big-bang refactor
DEFECT-007 ──→ Missing async standard (no lifecycle test)
DEFECT-008 ──→ Cross-layer integration gap (no auth-included tests)
DEFECT-009 ──→ Cross-layer integration gap (split-brain feature dev)
DEFECT-010 ──→ Big-bang refactor (lock discipline not enforced)
DEFECT-011 ──→ Incomplete remediation (cross-layer gap)
DEFECT-012 ──→ Big-bang refactor (parallel implementation)
DEFECT-013 ──→ Workaround-as-fix (no systemic cause — one-off)
DEFECT-014 ──→ No input validation standard for WebSocket
DEFECT-015 ──→ Big-bang refactor (shared mutable state)
DEFECT-016 ──→ Cross-layer integration gap (config vs application)
DEFECT-017 ──→ Enhancement checklist (never-completed component)
```

---

## Most Leveraged Single Fix

Adding **mypy or pyright to CI** with strict mode would catch:
- DEFECT-002 (undefined symbols → type errors)
- DEFECT-007 (unawaited coroutine → type error)
- DEFECT-010 (partially — can flag unsynchronized access patterns)
- Future instances of the big-bang refactor failure mode

Adding a single **integration test that runs the backend with `WEEBOT_API_KEY=test`** would catch:
- DEFECT-008 (auth proxy chain)
- DEFECT-009 (WebSocket token)
- DEFECT-016 (nginx header forwarding if tested through nginx)

Together, these two changes would prevent the most common failure patterns in this codebase.
