# VerifyingState 401 Fix — Architectural Plan

## Root Cause

The 401 is a **circuit-breaker cascade**, not a key-configuration bug:

```
Executor runs for 5+ minutes
  → xAI direct hits intermittent APIConnectionError (3 times)
  → CircuitBreaker opens for xAI (cooldown: 60s)
  → DirectOrFallbackAdapter routes ALL calls to OpenRouter
  → VerifyingState runs → OpenRouter → 401 (stale key)
```

The OpenRouter key itself may be valid, but the circuit breaker never resets because:
- The cooldown is 60s but the executor keeps hammering the breaker
- Every new call resets the cooldown timer
- Once the breaker is open, it stays open for the rest of the flow

## Architecture Review

```
┌─────────────────────────────────────────────────────────────┐
│  DirectOrFallbackAdapter                                    │
│  ┌──────────────┐     failure      ┌──────────────────┐    │
│  │  Primary      │ ──────────────→  │  Secondary        │    │
│  │  (xAI direct) │                  │  (OpenRouter)     │    │
│  └──────────────┘                  └──────────────────┘    │
│         ↑                                                    │
│  CircuitBreaker (3 failures → open, 60s cooldown)           │
└─────────────────────────────────────────────────────────────┘
```

The issue: `DirectOrFallbackAdapter.chat()` (line 88-120) tries primary first. When it fails, it checks `_secondary_has_key` (our fix from Phase 5), then falls back. But it never checks whether the **fallback itself is healthy** before routing ALL future traffic there.

## Fix Plan (3 changes, respecting Clean Architecture)

### Fix 1: Fallback health-gate (Infrastructure layer)

**File:** `weebot/infrastructure/adapters/llm/direct_or_fallback_adapter.py`

**Problem:** Once the primary breaker opens, ALL calls route to secondary even if secondary returns 401 on EVERY call.

**Fix:** Add a `_fallback_failure_count` counter. After N consecutive fallback failures, stop routing to the fallback and re-raise the primary error with a clear diagnostic message. This prevents the "silent 401 cascade" where 7+ calls all hit a dead endpoint.

```python
# In __init__:
self._fallback_failure_count = 0
self._MAX_FALLBACK_FAILURES = 3

# In chat(), before falling back:
if self._fallback_failure_count >= self._MAX_FALLBACK_FAILURES:
    logger.error(
        "%s: fallback (OpenRouter) has failed %d consecutive times. "
        "Refusing further fallback — re-raising primary error.",
        self._label, self._fallback_failure_count,
    )
    raise  # let primary error propagate

# After fallback attempt:
try:
    return await self._secondary.chat(model=model, **shared)
    self._fallback_failure_count = 0  # success → reset
except Exception:
    self._fallback_failure_count += 1
    raise
```

**Architecture compliance:** Infrastructure layer only — no Domain or Application changes. The adapter handles its own resilience.

### Fix 2: Circuit breaker half-open probing (Infrastructure layer)

**File:** `weebot/core/circuit_breaker.py`

**Problem:** The circuit breaker uses a simple open/closed model. Once open, it stays open for `cooldown_seconds` (60s). There's no half-open state where a single probe call tests if the service has recovered.

**Fix:** Implement the standard 3-state circuit breaker pattern (closed → open → half-open → closed). After `cooldown_seconds` elapse, transition to **half-open** and allow ONE probe call. If the probe succeeds → close the breaker. If it fails → stay open.

```python
class BreakerState(Enum):
    CLOSED = "closed"       # normal operation
    OPEN = "open"           # all calls rejected
    HALF_OPEN = "half_open" # one probe call allowed

class CircuitBreaker:
    def __init__(self, failure_threshold=3, cooldown_seconds=60.0, probe_timeout=5.0):
        self.state = BreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        self._cooldown = cooldown_seconds
        self._probe_timeout = probe_timeout

    async def call(self, fn, *args, **kwargs):
        if self.state == BreakerState.OPEN:
            if self._cooldown_elapsed():
                self.state = BreakerState.HALF_OPEN
                logger.info("Circuit breaker half-open — allowing probe call")
            else:
                raise CircuitBreakerOpen(...)

        if self.state == BreakerState.HALF_OPEN:
            try:
                result = await asyncio.wait_for(fn(*args, **kwargs), self._probe_timeout)
                self.state = BreakerState.CLOSED
                self._failure_count = 0
                logger.info("Circuit breaker closed — probe succeeded")
                return result
            except Exception:
                self.state = BreakerState.OPEN
                self._last_failure_time = time.time()
                logger.warning("Circuit breaker probe failed — staying open")
                raise CircuitBreakerOpen(...)

        # CLOSED state — normal operation
        try:
            result = await fn(*args, **kwargs)
            self._failure_count = 0
            return result
        except Exception:
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self.state = BreakerState.OPEN
                self._last_failure_time = time.time()
                logger.warning("Circuit breaker opened after %d failures", self._failure_count)
            raise
```

**Architecture compliance:** Core layer (cross-cutting concern) — no Domain or Application changes. The circuit breaker is a standalone utility with no dependencies on business logic.

### Fix 3: VerifyingState graceful degradation (Application layer)

**File:** `weebot/application/flows/states/verifying.py`

**Problem:** When verification fails due to LLM errors (not task quality), the VerifyingState retries 7+ times before giving up. Each retry burns 10+ seconds on a dead endpoint.

**Fix:** Add an `_auth_error_count` tracker. After 2 consecutive auth errors (401/403), skip verification with a warning instead of retrying.

```python
# In VerifyingState.execute():
_auth_error_count = 0
_MAX_AUTH_RETRIES = 2

for attempt in range(max_retries):
    try:
        response = await flow._llm.chat(messages=[...])
        _auth_error_count = 0  # reset on success
        # ... process verification result
    except AuthenticationError:
        _auth_error_count += 1
        if _auth_error_count >= _MAX_AUTH_RETRIES:
            logger.warning(
                "Verification skipped: %d consecutive auth errors. "
                "Check OPENROUTER_API_KEY and XAI_API_KEY.",
                _auth_error_count,
            )
            yield VerdictEvent(verdict="skipped", reason="auth_error")
            return
        continue
```

**Architecture compliance:** Application layer — the VerifyingState already handles errors within its flow logic. This just tightens the error-handling policy.

## Implementation Order

| Step | File | Effort | Risk |
|------|------|--------|------|
| 1 | `direct_or_fallback_adapter.py` — fallback failure counter | 15 min | Low |
| 2 | `circuit_breaker.py` — half-open state | 30 min | Medium — changes failure behavior |
| 3 | `verifying.py` — auth error early exit | 10 min | Low |

## Verification

After implementation, run a long flow task. The VerifyingState should:
- NOT show 7 consecutive 401 errors
- Either succeed (if keys are valid) or skip with a clear warning after 2 auth errors
- The circuit breaker should show "half-open" → "closed" transitions in logs when xAI recovers

## Alternative: Quick non-architectural fix

If the architectural fixes are too invasive, a simpler approach:

In `verifying.py`, catch `AuthenticationError` on the first attempt and immediately transition to `CompletedState` with a warning instead of retrying. This is a 3-line change:

```python
except AuthenticationError:
    logger.warning("Skipping LLM verification — API key invalid")
    yield VerdictEvent(verdict="skipped", reason="auth_error")
    return
```
