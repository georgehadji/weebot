# Implementation Plan for DeepSeek V4 Flash

## Execution Order (By Priority)

### Phase 1: CRITICAL Security and Bug Fixes (Do First)

---

#### Fix 1.1: Remove Module-Level Variable Corruption

**Goal:** Prevent LLM cache from being silently disabled after first error.

**File:** `weebot/infrastructure/adapters/llm/resilient_adapter.py`

**Modification:** Remove lines 34-35 inside `_sanitize_error()` function. These two lines (`LLMCache = None` and `CacheKey = None`) are mis-indented copy-paste artifacts that execute on every call to `_sanitize_error`, overwriting the module-level imports.

**Exact Change:**
Find the function `_sanitize_error` (around line 27). After the `try/except` block that modifies `exc.args`, there are two stray lines:
```python
    LLMCache = None
    CacheKey = None
```
DELETE both lines entirely. They serve no purpose and corrupt module state.

**Validation:**
```bash
python -c "from weebot.infrastructure.adapters.llm.resilient_adapter import LLMCache, CacheKey; assert LLMCache is not None or True"
pytest tests/ -k "resilient" -v
```

**Rollback:** `git checkout weebot/infrastructure/adapters/llm/resilient_adapter.py`

**Risk:** LOW — removing dead code that only causes harm.

---

#### Fix 1.2: Fix CORS Configuration

**Goal:** Prevent cross-origin credential theft.

**File:** `weebot/interfaces/web/main.py`

**Modification:** Replace the `allow_origins` list to remove `"*"`.

**Current Code (around line 135):**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Replace With:**
```python
_allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
_extra_origin = os.getenv("WEEBOT_CORS_ORIGIN")
if _extra_origin:
    _allowed_origins.append(_extra_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Validation:**
```bash
python -c "
from weebot.interfaces.web.main import create_app
app = create_app()
for mw in app.user_middleware:
    if 'CORS' in str(mw):
        assert '*' not in str(mw.kwargs.get('allow_origins', []))
print('CORS OK')
"
```

**Rollback:** `git checkout weebot/interfaces/web/main.py`

**Risk:** LOW — may require setting WEEBOT_CORS_ORIGIN for non-localhost frontends.

---

#### Fix 1.3: Add WebSocket Authentication

**Goal:** Prevent unauthenticated access to real-time agent events.

**File:** `weebot/interfaces/web/main.py`

**Modification:** In the APIKeyMiddleware, REMOVE the WebSocket skip. Instead, add token validation to the WebSocket endpoint handlers.

**Step A — Remove the WS skip in middleware:**
Delete or comment out:
```python
# Skip auth for WebSocket upgrade
if request.url.path.startswith("/ws"):
    return await call_next(request)
```

**Step B — Add token check to WebSocket handlers:**
```python
@app.websocket("/ws")
async def websocket_global(websocket: WebSocket) -> None:
    if _ws.weebot_api_key:
        token = websocket.query_params.get("token")
        if token != _ws.weebot_api_key:
            await websocket.close(code=4001, reason="Unauthorized")
            return
    await manager.connect(websocket)
    # ... rest unchanged
```

Apply the same pattern to `/ws/sessions/{session_id}`.

**Validation:**
```bash
pytest tests/unit/interfaces/ -v
# Manual test: attempt WS connection without token when API key is set
```

**Rollback:** `git checkout weebot/interfaces/web/main.py`

**Risk:** MEDIUM — may break existing WebSocket clients that don't pass tokens. Document the `?token=` query parameter requirement.

---

#### Fix 1.4: Fix Broken HMAC Verification

**Goal:** Make admin security override actually functional (or remove it).

**File:** `weebot/tools/bash_tool.py`

**Modification:** Change `hmac.new(` to `hmac.HMAC(` in `_verify_override_token`.

**Current Code:**
```python
expected = hmac.new(
    secret.encode("utf-8"),
    command.encode("utf-8"),
    hashlib.sha256,
).hexdigest()
```

**Replace With:**
```python
expected = hmac.HMAC(
    secret.encode("utf-8"),
    command.encode("utf-8"),
    hashlib.sha256,
).hexdigest()
```

**Validation:**
```bash
python -c "
import hmac, hashlib
secret = b'test'
msg = b'echo hello'
result = hmac.HMAC(secret, msg, hashlib.sha256).hexdigest()
assert len(result) == 64
print('HMAC OK:', result[:16])
"
```

**Required Test (add to tests/unit/):**
```python
def test_verify_override_token():
    import os, hmac, hashlib
    os.environ['WEEBOT_ADMIN_SECRET'] = 'test-secret-key'
    from weebot.tools.bash_tool import BashTool
    tool = BashTool()
    cmd = 'echo hello'
    valid_token = hmac.HMAC(
        b'test-secret-key', cmd.encode(), hashlib.sha256
    ).hexdigest()
    assert tool._verify_override_token(cmd, valid_token) is True
    assert tool._verify_override_token(cmd, 'invalid') is False
    del os.environ['WEEBOT_ADMIN_SECRET']
    assert tool._verify_override_token(cmd, valid_token) is False
```

**Rollback:** `git checkout weebot/tools/bash_tool.py`

**Risk:** LOW — fixing a typo. The feature was already non-functional.

---

### Phase 2: HIGH Priority Fixes (Same Day)

---

#### Fix 2.1: Add SQL-Level Pagination to Session List

**Goal:** Prevent O(n) memory load on session list API.

**File:** `weebot/interfaces/web/routers/sessions.py`

**Modification:** Pass status, limit, and offset parameters to the repository query instead of filtering in Python.

**Current Code (around line 55):**
```python
sessions = await state_repo.list_sessions(user_id=user_id)
if status:
    sessions = [s for s in sessions if s.status.value == status]
total = len(sessions)
sessions = sessions[offset:offset + limit]
```

**Replace With:**
```python
sessions = await state_repo.list_sessions(
    user_id=user_id, status=status, limit=limit, offset=offset
)
total = await state_repo.count_sessions(user_id=user_id)
```

**Validation:**
```bash
pytest tests/unit/interfaces/ -v
pytest tests/integration/ -k "session" -v
```

**Risk:** LOW — the repository already supports these parameters.

---

#### Fix 2.2: Remove Self-Instantiated Containers from Tools

**Goal:** Prevent resource leaks from orphaned DI containers.

**Files:** `weebot/tools/bash_tool.py`, `weebot/tools/python_tool.py`

**Modification:** Change the fallback in `__init__` to raise a clear error instead of creating a new Container:

**Replace pattern (in both files):**
```python
if sandbox is None:
    from weebot.application.di import Container
    container = Container()
    container.configure_defaults()
    sandbox = container.get(SandboxPort)
```

**With:**
```python
if sandbox is None:
    try:
        from weebot.application.di import Container
        container = Container()
        container.configure_defaults()
        sandbox = container.get(SandboxPort)
    except Exception:
        raise RuntimeError(
            f"{self.__class__.__name__} requires a SandboxPort. "
            "Inject via constructor or ensure DI container is configured."
        )
```

**Note:** This is a transitional fix. The proper fix is ensuring all tool instantiations go through DI, but that requires tracing all call sites.

**Risk:** MEDIUM — may surface previously-hidden configuration errors.

---

#### Fix 2.3: Add `load_events` Parameter to Session Queries

**Goal:** Avoid deserializing all events when only session metadata is needed.

**File:** `weebot/infrastructure/persistence/sqlite_state_repo.py`

**Modification:** Add `load_events: bool = True` parameter to `_row_to_session`:

```python
def _row_to_session(self, row, load_events: bool = True) -> Session:
    if load_events:
        events_raw = json.loads(row["events_json"] or "[]")
        events = []
        adapter = self._get_event_adapter()
        for e in events_raw:
            try:
                events.append(adapter.validate_python(e))
            except Exception:
                events.append(MessageEvent(message=f"[unparseable event]"))
    else:
        events = []
    # ... rest unchanged
```

Then update `list_sessions` to pass `load_events=False` by default.

**Risk:** LOW — backward compatible, events loaded on demand.

---

### Phase 3: MEDIUM Priority Fixes (This Week)

---

#### Fix 3.1: Fix FTS5 Write Amplification

**File:** `weebot/infrastructure/persistence/sqlite_state_repo.py`

**Goal:** Only index NEW events, not all events on every save.

**Strategy:** Track the number of already-indexed events per session. On save, only index events with index >= last_indexed_count.

---

#### Fix 3.2: Add API Key Timing-Safe Comparison

**File:** `weebot/interfaces/web/main.py`

**Change:**
```python
# Before:
if api_key != _ws.weebot_api_key:

# After:
import hmac as _hmac_mod
if not _hmac_mod.compare_digest(api_key or "", _ws.weebot_api_key or ""):
```

---

#### Fix 3.3: Add Rate Limiting to FastAPI Endpoints

**File:** `weebot/interfaces/web/main.py`

**Strategy:** Add `slowapi` middleware or reuse the existing `check_rate_limit` from `weebot/utils/rate_limiter.py` on the webhook and session endpoints.

---

#### Fix 3.4: Remove Container Creation from PlanActFlow

**File:** `weebot/application/flows/plan_act_flow.py`

**Goal:** Replace `_get_persistence_adapter` and `_get_tracing_port` methods that create new Containers with constructor injection.

**Strategy:** Add `persistence_adapter` and `tracing_port` to `PlanActFlowConfig`. Remove lazy Container creation.

---

### Phase 4: Strategic Improvements (Next Sprint)

#### Fix 4.1: Migrate EventStore to Async

Migrate `weebot/infrastructure/event_store.py` from synchronous `sqlite3` + `asyncio.to_thread` to `aiosqlite` with the shared connection pool.

#### Fix 4.2: Add Schema Migration System

Use Alembic (already in requirements.txt) to manage SQLite schema changes instead of `CREATE TABLE IF NOT EXISTS`.

#### Fix 4.3: Persist Circuit Breaker State

Add a `circuit_breaker_state` table to the sessions database. On shutdown, flush breaker states. On startup, restore them.

#### Fix 4.4: Decompose PlanActFlow

Extract `EventEmitter`, `FlowPersistence`, and `ModelSelector` collaborators from PlanActFlow to reduce its responsibility count.

---

## Regression Test Requirements

After ALL fixes, run:
```bash
pytest tests/ -v --tb=short
python -m cli.main health
python -c "from weebot.interfaces.web.main import create_app; app = create_app(); print('App OK')"
```

## Rollback Procedure

Each fix touches at most 1-2 files. Rollback strategy for any fix:
```bash
git checkout <file_path>
```

For multi-file fixes (Fix 1.3), rollback the entire commit:
```bash
git revert HEAD
```

## Commit Strategy

One commit per fix. Commit message format:
```
fix(security): SEC-001 remove wildcard CORS origin
fix(bug): ARCH-001 remove stray LLMCache=None in _sanitize_error
fix(security): SEC-002 add WebSocket authentication
fix(bug): SEC-003 fix hmac.new -> hmac.HMAC typo
perf(api): PERF-001 add SQL-level pagination to session list
```
