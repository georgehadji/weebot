# Reliability Review

**Codebase:** Weebot AI Agent Framework  
**Assessment Date:** 2025-07-21

---

## Finding REL-001: Silent Session Persistence Failures

**Severity:** HIGH  
**Probability:** Medium (occurs on SQLite busy or disk full)  
**Location:** `weebot/application/flows/plan_act_flow.py` (`_emit` method)

### Evidence
```python
if self._state_repo:
    async with self._emit_lock:
        adapter = self._get_persistence_adapter()
        if adapter is not None:
            ok = await adapter.save_session(self._session)
            if not ok:
                self._log.error(
                    "Session %s dead-lettered — persistence exhausted retries",
                    self._session.id,
                )
        else:
            try:
                await self._state_repo.save_session(self._session)
            except Exception as exc:
                self._log.warning(
                    "Session persistence failed (retryable): %s", exc
                )
```

### Failure Mode
When persistence fails:
1. The flow continues executing (no exception raised)
2. Only a warning is logged
3. If the process crashes AFTER this point, all session state since the last successful save is lost
4. The user sees successful tool execution but the session state may be inconsistent on restart

### Impact
- Data loss risk on any persistence failure
- No alerting — requires log monitoring to detect
- Checkpoint saves may also fail silently (caught by bare `except Exception`)

### Remediation
1. Track consecutive persistence failures — if >3, pause the flow and surface to user
2. Emit a domain event for persistence failure (so monitors can alert)
3. Consider in-memory journal that replays on next startup

---

## Finding REL-002: Circuit Breaker State Lost on Restart

**Severity:** MEDIUM  
**Probability:** High (happens on every restart)  
**Location:** `weebot/core/circuit_breaker.py`

### Evidence
```python
class CircuitBreaker:
    def __init__(self, ...):
        self._breakers: Dict[str, _BreakerEntry] = {}  # In-memory only
```

### Failure Mode
1. A model experiences 3 consecutive failures → circuit opens
2. Application restarts (deployment, crash, manual restart)
3. Circuit state is lost → immediately routes traffic to the failing model
4. 3 more failures before circuit opens again = 3 wasted requests + latency

### Impact
- On restart after outage, all circuit breakers reset to CLOSED
- Initial burst of failures before protection re-engages
- Thundering herd effect if multiple instances restart simultaneously

### Remediation
- Persist circuit state to the existing SQLite database
- On startup, load breaker states and honor any OPEN circuits with remaining cooldown
- Or: accept this as a known limitation for single-instance deployments (document it)

---

## Finding REL-003: No Health Check for Database Connectivity

**Severity:** MEDIUM  
**Probability:** Low (SQLite is embedded)  
**Location:** `weebot/interfaces/web/routers/health.py` (assumed)

### Evidence
The health endpoint exists but I was unable to verify whether it checks database connectivity. For SQLite, common failure modes include:
- Disk full
- WAL file corruption
- File permissions changed
- Database locked by external process

### Remediation
Health check should:
1. Attempt a read query (`SELECT 1`)
2. Verify WAL file exists and is not corrupted
3. Check disk space available

---

## Finding REL-004: No Graceful Degradation for LLM Failures

**Severity:** MEDIUM  
**Probability:** Medium (API outages happen weekly)  
**Location:** `weebot/infrastructure/adapters/llm/resilient_adapter.py`

### Evidence
The resilient adapter implements retry and circuit breaker, but when ALL retries are exhausted:
1. Exception propagates up to the Plan-Act flow
2. Flow emits an `ErrorEvent`
3. Session is left in an inconsistent state (plan may be partially executed)

### Missing Capabilities
- No automatic fallback to a different model provider
- No "safe mode" that pauses execution and waits for manual intervention
- No partial result preservation (completed steps are checkpointed, but in-progress step output is lost)

### Remediation
1. Implement cascading adapter (try OpenRouter → direct API → different model)
2. On total LLM failure, transition flow to WAITING state with a clear error message
3. Preserve any partial step output in the checkpoint

---

## Finding REL-005: Scheduler Has No Dead Letter Queue

**Severity:** MEDIUM  
**Probability:** Medium (any exception in job callable)  
**Location:** `weebot/scheduling/scheduler.py` (`_execute_job`)

### Evidence
```python
except Exception as exc:
    logger.error("Job execution failed: %s: %s", job_id, exc)
    job.status = JobStatus.FAILED.value
    job.error_count += 1
    job.last_error = str(exc)
```

### Failure Mode
- Failed jobs are marked as FAILED but remain scheduled
- On next trigger, they execute again (potentially failing again)
- No exponential backoff between retries of the same failed job
- No maximum failure count before disabling the job
- No notification to the user that a scheduled job is failing

### Remediation
1. Add `max_consecutive_failures` — after N failures, auto-pause the job
2. Add exponential backoff between retries of a failed job
3. Emit a notification on job failure (Telegram, Windows toast)

---

## Finding REL-006: WebSocket Manager Has No Connection Limits

**Severity:** LOW  
**Probability:** Low (requires intentional abuse)  
**Location:** `weebot/interfaces/web/websocket.py` (assumed)

### Evidence
The WebSocket manager accepts unlimited connections. There is no:
- Maximum connection count
- Per-IP connection limit
- Idle timeout for inactive connections
- Heartbeat/ping-pong mechanism

### Failure Mode
- Memory exhaustion from thousands of open WebSocket connections
- File descriptor exhaustion on the OS level
- Event broadcasting slows linearly with connection count

### Remediation
- Add maximum connection limit (e.g., 100)
- Implement idle timeout (disconnect after 5 minutes without messages)
- Add ping/pong keepalive mechanism

---

## Finding REL-007: No Observability for Event Bus Lag

**Severity:** LOW  
**Probability:** Low  
**Location:** `weebot/infrastructure/event_bus.py`

### Evidence
No metrics are emitted for:
- Event bus queue depth
- Time between event publish and subscriber receipt
- Subscriber error count
- Dropped events

### Impact
Performance degradation is invisible until it causes user-visible issues.

### Remediation
- Add `event_bus_publish_duration_seconds` histogram
- Add `event_bus_subscriber_errors_total` counter
- Add `event_bus_queue_depth` gauge (if buffered)

---

## Finding REL-008: Global Pool Registry Memory Leak on Process Fork

**Severity:** LOW  
**Probability:** Low (only if using multiprocessing)  
**Location:** `weebot/infrastructure/persistence/connection_pool.py`

### Evidence
```python
_pool_registry: dict[str, SQLiteConnectionPool] = {}
_pool_lock = asyncio.Lock()
```

### Failure Mode
- Module-level dict holds references to all created pools
- Pools are never removed from the registry (only `close_all_pools` clears it)
- If the application creates pools for temporary databases (e.g., test runs), they accumulate
- The asyncio.Lock is not fork-safe — child processes inherit a potentially locked Lock

### Impact
- Low for single-process deployments
- Problematic for test suites that create many temporary databases

---

## Reliability Scorecard

| Dimension | Score | Notes |
|-----------|-------|-------|
| **Retry Logic** | 7/10 | Good exponential backoff with jitter |
| **Circuit Breaking** | 8/10 | Well-implemented, missing persistence |
| **Graceful Degradation** | 4/10 | No cascading, failures propagate |
| **Data Durability** | 5/10 | Silent failures, no WAL integrity checks |
| **Monitoring** | 6/10 | Prometheus metrics exist but gaps remain |
| **Recovery** | 5/10 | Checkpoints exist but untested edge cases |
| **Load Management** | 3/10 | No backpressure, no connection limits |

**Overall Reliability Score: 5.4/10** — Adequate for development/single-user, not production-ready.
