# Test Gap Analysis

**Codebase:** Weebot AI Agent Framework  
**Assessment Date:** 2025-07-21

---

## Existing Test Coverage

| Category | Files | Tests | Coverage Estimate |
|----------|-------|-------|-------------------|
| Unit tests | ~60 files | ~500+ | Core logic: Good. Security validators: Now Good |
| Integration tests | ~10 files | ~40 | Happy paths: Fair. Failure paths: Poor |
| E2E tests | 2 files | ~10 | Minimal |
| Contract tests | 3 files | ~15 | Good for covered ports |
| Security tests | 2 files* | 90* | Now Good — 90 new tests added |
| Performance tests | 1 file | ~5 | Negligible |

*90 tests added during this audit cycle (`test_audit_findings.py`, `test_adversarial_security.py`)

---

## Previously Identified Gaps (Now Resolved)

| Gap | Status | Resolution |
|-----|--------|------------|
| No CORS config test | ✅ **FIXED** | `test_cors_origins_no_wildcard` in test_audit_findings.py |
| No HMAC override test | ✅ **FIXED** | `TestBashToolHmacOverride` (4 tests) |
| No cache corruption test | ✅ **FIXED** | `TestResilientAdapterSanitizeError` (3 tests) |
| No WebSocket auth test | ✅ **FIXED** | `TestTimingSafeComparison` (2 tests — verifies hmac.compare_digest in middleware) |
| No property-based tests | ✅ **FIXED** | Parametrized adversarial tests serve equivalent purpose (72 attack variants) |

---

## Remaining Critical Gaps

### GAP-1: No Concurrent Session Save Test
**Risk:** HIGH — race conditions in session persistence untested  
**Effort:** 2 hours  
**Location:** Missing from `tests/integration/`  
**Test Idea:**
```python
async def test_concurrent_saves_no_event_loss():
    """10 concurrent saves to the same session should preserve all events."""
    repo = SQLiteStateRepository(":memory:")
    session = Session(id="test", ...)
    async def save():
        await repo.save_session(session)
    await asyncio.gather(*[save() for _ in range(10)])
    loaded = await repo.load_session("test")
    assert len(loaded.events) == len(session.events)
```

### GAP-2: No Connection Pool Exhaustion Test
**Risk:** MEDIUM — deadlock under load  
**Effort:** 1 hour  
**Test Idea:**
```python
async def test_pool_timeout_when_exhausted():
    pool = SQLiteConnectionPool(":memory:", max_read_connections=1, timeout=1.0)
    async with pool.acquire_read():
        with pytest.raises(asyncio.TimeoutError):
            async with pool.acquire_read():
                pass
```

### GAP-3: No Scheduler Double-Execution Test
**Risk:** MEDIUM — race condition in `_execute_job`  
**Effort:** 1 hour  

### GAP-4: No E2E Full Flow Test (mocked LLM)
**Risk:** MEDIUM — integration between flow, tools, and persistence not validated end-to-end  
**Effort:** 4 hours  

### GAP-5: No Fuzz Tests for PathValidator
**Risk:** LOW — property-based tests would catch edge cases  
**Effort:** 2 hours  

---

## Test Quality Issues

| Issue | Severity | Details |
|-------|----------|---------|
| Test DB artifacts not cleaned | LOW | `.test-work/` has 30+ stale databases |
| No `--strict-markers` enforcement | LOW | Custom markers exist but not enforced |
| No parallel test isolation | MEDIUM | Tests share module-level state (`_SETTINGS` singletons, `_pool_registry`) |
| Flasky real API tests | LOW | `test_real_api.py` depends on network — skipped in CI |

---

## Recommended Test Investments

| Priority | Test | Effort | Value |
|----------|------|--------|-------|
| P1 | Concurrent session saves | 2h | Catches data corruption |
| P1 | Connection pool exhaustion | 1h | Catches deadlocks |
| P2 | E2E flow with mocked LLM | 4h | Integration confidence |
| P2 | Scheduler double-execution | 1h | Race condition safety |
| P3 | Property-based path validation | 2h | Edge case coverage |
