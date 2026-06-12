# Performance Review

**Codebase:** Weebot AI Agent Framework  
**Assessment Date:** 2025-07-21

---

## Finding PERF-001: Session List Loads All Records Into Memory

**Severity:** HIGH  
**Estimated Impact:** O(n) memory and CPU as sessions grow  
**Location:** `weebot/interfaces/web/routers/sessions.py` (line ~55)

### Evidence
```python
@router.get("", response_model=SessionListResponse)
async def list_sessions(...):
    sessions = await state_repo.list_sessions(user_id=user_id)
    
    # Filter by status if provided — IN PYTHON, not SQL
    if status:
        sessions = [s for s in sessions if s.status.value == status]
    
    total = len(sessions)
    sessions = sessions[offset:offset + limit]
```

### Root Cause
The endpoint fetches ALL sessions from the database, deserializes every one (including all events JSON), then filters and paginates in Python.

### Impact at Scale
- 1,000 sessions × average 50KB events_json = 50MB loaded per API call
- JSON deserialization of events is the hot path (Pydantic TypeAdapter)
- Response time degrades linearly with session count

### Fix Strategy
Pass `status` and `limit`/`offset` to the SQL query:
```python
sessions = await state_repo.list_sessions(
    user_id=user_id, status=status, limit=limit, offset=offset
)
```
The repository already supports these parameters — the router just doesn't use them.

---

## Finding PERF-002: Full Event Deserialization on Every Session Load

**Severity:** HIGH  
**Estimated Impact:** ~2-10ms per session load, compounds with session list  
**Location:** `weebot/infrastructure/persistence/sqlite_state_repo.py` (`_row_to_session`)

### Evidence
```python
def _row_to_session(self, row) -> Session:
    events_raw = json.loads(row["events_json"] or "[]")
    events = []
    adapter = self._get_event_adapter()
    for e in events_raw:
        try:
            events.append(adapter.validate_python(e))
        except Exception:
            events.append(MessageEvent(message=f"[unparseable event: {type(e).__name__}]"))
```

### Root Cause
Every session load deserializes ALL events from JSON using Pydantic's TypeAdapter with discriminated unions. For sessions with 100+ events, this is significant CPU work.

### Impact
- Session listing becomes O(n × events_per_session)
- The `list_sessions` endpoint triggers this for every session
- 100 sessions × 100 events = 10,000 Pydantic validations per API call

### Fix Strategy
1. For list operations, add a `load_events=False` parameter that skips event deserialization
2. Load events only when explicitly requested (single session detail view)
3. Consider storing event count in a separate column for summary views

---

## Finding PERF-003: FTS5 Indexing in Write Path

**Severity:** MEDIUM  
**Estimated Impact:** +5-15ms per session save  
**Location:** `weebot/infrastructure/persistence/sqlite_state_repo.py` (`save_session`)

### Evidence
```python
async with pool.acquire_write() as conn:
    await conn.execute("""INSERT INTO sessions ... ON CONFLICT ... """, {...})
    
    # Index events for FTS5 search (M2)
    for event in session.events:
        # ...
        try:
            await index_event(conn, session.id, str(event_type), str(summary), content)
        except Exception:
            logger.warning("Failed to index event for FTS5", exc_info=True)
```

### Root Cause
Every `save_session` call re-indexes ALL events in the session (not just new ones). For a session with 50 events saved 50 times, that's 2,500 FTS5 insertions.

### Impact
- Write amplification: events are re-indexed on every save
- FTS5 table grows quadratically with session activity
- SQLite write lock held longer than necessary

### Fix Strategy
- Track which events have been indexed (by index or event ID)
- Only index new events (those added since last save)
- Consider moving FTS indexing to an async background task

---

## Finding PERF-004: Connection Pool Pre-Creates All Read Connections

**Severity:** LOW  
**Estimated Impact:** ~50ms startup delay per 5 connections  
**Location:** `weebot/infrastructure/persistence/connection_pool.py` (`initialize`)

### Evidence
```python
# Pre-create read connections
for i in range(self.max_read):
    conn = await aiosqlite.connect(str(self.db_path))
    conn.row_factory = aiosqlite.Row
    await self._read_pool.put(conn)
```

### Root Cause
All 5 read connections are created at pool initialization, regardless of whether they'll be used.

### Impact
- Slightly slower startup
- Holds resources (file descriptors, SQLite reader slots) that may not be needed
- For the typical single-user CLI use case, only 1-2 connections are ever used

### Fix Strategy
Use lazy connection creation: start with 0 connections in the pool, create on demand up to `max_read`.

---

## Finding PERF-005: Blocking Event Store Wrapped in asyncio.to_thread

**Severity:** MEDIUM  
**Estimated Impact:** Thread pool exhaustion under concurrent load  
**Location:** `weebot/infrastructure/event_store.py`

### Evidence
```python
class EventStore(EventStorePort):
    async def log_event(self, ...):
        return await asyncio.to_thread(self._sync_log_event, ...)
    
    async def get_session_events(self, ...):
        events = await asyncio.to_thread(self._sync_get_session_events, ...)
```

### Root Cause
The EventStore uses synchronous `sqlite3` connections wrapped in `asyncio.to_thread`. Each operation consumes a thread from the default thread pool (typically 40 threads). Under concurrent load, the thread pool can be exhausted.

### Impact
- Thread pool starvation under 40+ concurrent event store operations
- Each operation holds a sqlite3 connection open for the duration of the thread
- No connection pooling — each call opens and closes a connection
- GIL contention from multiple threads doing JSON serialization

### Fix Strategy
- Migrate to async aiosqlite (matching the state repo pattern)
- Or increase thread pool size and add connection pooling
- Or share the existing SQLiteConnectionPool infrastructure

---

## Finding PERF-006: events_json Bloat Guard Has Linear Scan

**Severity:** LOW  
**Estimated Impact:** ~1-5ms for large sessions  
**Location:** `weebot/infrastructure/persistence/sqlite_state_repo.py` (`save_session`)

### Evidence
```python
events_json = json.dumps(events_data, default=str)
while len(events_json) > MAX_EVENTS_JSON_BYTES and len(events_data) > 1:
    events_data = events_data[1:]
    events_json = json.dumps(events_data, default=str)  # Re-serializes entire list each iteration
```

### Root Cause
The truncation loop re-serializes the entire events list on each iteration until it fits the size limit. For a 10MB events_json that needs to shrink to 1MB, this could require many iterations of full JSON serialization.

### Fix Strategy
Use binary search or estimate bytes-per-event to jump closer to the target:
```python
if len(events_json) > MAX_EVENTS_JSON_BYTES:
    ratio = MAX_EVENTS_JSON_BYTES / len(events_json)
    keep = max(1, int(len(events_data) * ratio * 0.9))
    events_data = events_data[-keep:]
    events_json = json.dumps(events_data, default=str)
```

---

## Finding PERF-007: Regex Compilation in BashGuard Constructor

**Severity:** LOW (one-time cost)  
**Estimated Impact:** Negligible after first instantiation  
**Location:** `weebot/core/bash_guard.py`

### Assessment
BashGuard compiles ~30 regex patterns in its constructor. Since BashTool creates a new BashGuard on each instantiation, and BashTool may be instantiated multiple times (in DI container, in MCP server, in sub-agent factory), the regex compilation happens multiple times.

### Fix Strategy
Make `_compiled_patterns` a class-level cache keyed on the pattern list, or ensure BashGuard is a singleton via DI.

---

## Performance Optimization Roadmap

### Quick Wins (< 1 hour each)
1. Pass `status`/`limit`/`offset` to SQL in session list endpoint
2. Add `load_events=False` parameter for session summaries
3. Fix FTS5 to only index new events

### Medium Effort (2-4 hours)
4. Replace events_json truncation loop with ratio-based approach
5. Migrate EventStore to aiosqlite
6. Add lazy connection creation to pool

### Strategic Improvements (1-2 days)
7. Separate event storage from session state (normalize schema)
8. Add Redis/in-memory cache layer for hot session data
9. Implement event sourcing properly (append-only events, materialized session views)
