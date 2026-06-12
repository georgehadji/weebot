# Testing Gaps Analysis

**Codebase:** Weebot AI Agent Framework  
**Assessment Date:** 2025-07-21

---

## Test Infrastructure Overview

| Category | Files Found | Coverage Estimate |
|----------|-------------|-------------------|
| Unit tests | ~60+ files | Medium (core paths covered) |
| Integration tests | ~10 files | Low (happy paths only) |
| E2E tests | 2 files | Very Low |
| Contract tests | 3 files (ports) | Good for covered ports |
| Security tests | 2 files | Low |
| Performance tests | 1 file (smoke) | Negligible |

---

## Critical Missing Tests

### GAP-001: No Test for CORS Configuration

**Risk:** CRITICAL  
**Impact:** CORS misconfiguration (SEC-001) went undetected  
**Location:** Missing from `tests/unit/interfaces/`

**What to add:**
```python
def test_cors_does_not_allow_wildcard_with_credentials():
    """Verify CORS doesn't allow arbitrary origins with credentials."""
    from weebot.interfaces.web.main import create_app
    app = create_app()
    # Find CORS middleware and assert origins don't include "*"
    # when allow_credentials=True
```

---

### GAP-002: No Test for WebSocket Authentication

**Risk:** CRITICAL  
**Impact:** WebSocket auth bypass (SEC-002) went undetected  
**Location:** Missing from `tests/unit/interfaces/`

**What to add:**
```python
@pytest.mark.asyncio
async def test_websocket_requires_auth_when_api_key_set():
    """WebSocket connections should be rejected without valid token."""
    # Set WEEBOT_API_KEY, attempt WS connection without token
    # Assert connection is refused
```

---

### GAP-003: No Test for `_verify_override_token`

**Risk:** HIGH  
**Impact:** Broken HMAC code (SEC-003) went undetected  
**Location:** Missing from `tests/unit/`

**What to add:**
```python
def test_verify_override_token_valid():
    """Valid HMAC token should be accepted."""
    import hmac, hashlib, os
    os.environ["WEEBOT_ADMIN_SECRET"] = "test-secret"
    tool = BashTool()
    command = "echo hello"
    token = hmac.HMAC(b"test-secret", command.encode(), hashlib.sha256).hexdigest()
    assert tool._verify_override_token(command, token) is True

def test_verify_override_token_invalid():
    """Invalid token should be rejected."""
    os.environ["WEEBOT_ADMIN_SECRET"] = "test-secret"
    tool = BashTool()
    assert tool._verify_override_token("echo hello", "bad-token") is False
```

---

### GAP-004: No Test for Resilient Adapter Cache Corruption Bug

**Risk:** HIGH  
**Impact:** Silent cache degradation went undetected  
**Location:** Missing from `tests/unit/infrastructure/`

**What to add:**
```python
def test_sanitize_error_does_not_corrupt_module_globals():
    """_sanitize_error should not modify LLMCache or CacheKey globals."""
    from weebot.infrastructure.adapters.llm import resilient_adapter
    original_cache = resilient_adapter.LLMCache
    original_key = resilient_adapter.CacheKey
    
    resilient_adapter._sanitize_error(Exception("api_key=sk-12345678901234567890"))
    
    assert resilient_adapter.LLMCache is original_cache
    assert resilient_adapter.CacheKey is original_key
```

---

### GAP-005: No Concurrent Session Test

**Risk:** MEDIUM  
**Impact:** Race conditions in session persistence untested  
**Location:** Missing from `tests/integration/`

**What to add:**
```python
@pytest.mark.asyncio
async def test_concurrent_session_saves_dont_corrupt():
    """Multiple concurrent saves to the same session should not lose events."""
    # Create session, spawn 10 concurrent save operations
    # Verify all events are preserved
```

---

### GAP-006: No Test for Connection Pool Exhaustion

**Risk:** MEDIUM  
**Impact:** Deadlock under load untested  
**Location:** Missing from `tests/unit/infrastructure/`

**What to add:**
```python
@pytest.mark.asyncio
async def test_pool_timeout_when_all_connections_busy():
    """Pool should raise TimeoutError, not deadlock, when exhausted."""
    pool = SQLiteConnectionPool(":memory:", max_read_connections=1, timeout=1.0)
    await pool.initialize()
    
    async with pool.acquire_read():
        with pytest.raises(asyncio.TimeoutError):
            async with pool.acquire_read():
                pass
```

---

### GAP-007: No Test for Scheduler Concurrent Execution Guard

**Risk:** MEDIUM  
**Impact:** Double-execution race condition untested  
**Location:** `tests/unit/` (existing test_nl_cron.py covers NL parsing only)

**What to add:**
```python
@pytest.mark.asyncio
async def test_scheduler_prevents_double_execution():
    """_execute_job should skip if job is already in _running_jobs."""
    manager = SchedulingManager(db_path=tmp_path / "test.db")
    # Manually add job_id to _running_jobs
    manager._running_jobs.add("test-job")
    # Attempt execution — should skip
    await manager._execute_job("test-job")
    # Verify callable was NOT invoked
```

---

### GAP-008: No Property-Based Tests for Security Validators

**Risk:** MEDIUM  
**Impact:** Edge cases in path validation may be missed  
**Location:** Missing from `tests/unit/`

**What to add (using Hypothesis):**
```python
from hypothesis import given, strategies as st

@given(st.text(min_size=1, max_size=200))
def test_path_validator_never_allows_traversal(path_str):
    """No input should allow escaping the workspace."""
    validator = PathValidator(workspace_root=Path("/safe/workspace"))
    result = validator.validate(path_str)
    if result.result == ValidationResult.VALID:
        resolved = Path(result.sanitized_value).resolve()
        assert str(resolved).startswith("/safe/workspace")
```

---

### GAP-009: No Test for MCP Rate Limiting

**Risk:** LOW  
**Impact:** Rate limiting configuration errors untested  
**Location:** Missing from `tests/unit/interfaces/`

---

### GAP-010: No E2E Test for Full Flow with Real LLM

**Risk:** LOW  
**Impact:** Integration issues between flow and LLM may surface only in production  
**Note:** The existing `tests/integration/test_real_api.py` exists but is likely skip-marked for CI

---

## Existing Test Quality Issues

### Issue: Flaky Test Infrastructure
The `.test-work/` directory contains 30+ scheduler test databases, suggesting tests create persistent state that isn't reliably cleaned up. This can cause flaky tests when run in parallel.

### Issue: Missing Fixtures for Common Patterns
Many tests likely instantiate `Container()` directly. A shared fixture that provides a pre-configured test container would reduce boilerplate and ensure consistent test isolation.

### Issue: No Mutation Testing
Without mutation testing, code coverage alone doesn't guarantee test effectiveness. Critical security code (BashGuard patterns, PathValidator) should be mutation-tested.

---

## Testing Priority Recommendations

| Priority | Test | Effort | Impact |
|----------|------|--------|--------|
| P0 | CORS config validation | 30 min | Prevents security regression |
| P0 | HMAC override token | 30 min | Catches broken security code |
| P0 | Module variable corruption | 30 min | Catches cache bug regression |
| P1 | WebSocket auth | 1 hour | Prevents auth bypass regression |
| P1 | Concurrent session saves | 2 hours | Catches data corruption |
| P1 | Connection pool exhaustion | 1 hour | Catches deadlocks |
| P2 | Property-based path validation | 2 hours | Finds edge cases |
| P2 | Scheduler double-execution | 1 hour | Catches race conditions |
| P3 | Full E2E with mocked LLM | 4 hours | Integration confidence |
