# ARCH-AUDIT-V2-DEFECTS — Defect Remediation Plan

**Version:** 1.0
**Date:** 2026-07-12
**Scope:** Fix 2 VERIFIED-STATIC + 1 likely-missed defect from static audit of 77b16c4..cd29b31
**Epistemic protocol:** EGFV — every non-trivial claim labeled
**Auditor:** Precision Defect Auditor V2 (static / no-execution)

---

## Executive Summary

A static audit of the ARCH-AUDIT-V2 implementation surface (`77b16c4`..`cd29b31`)
found **2 VERIFIED-STATIC defects** and **1 HYPOTHESIS defect**.  All three are
reachable from production entry points and have minimal, surgical fixes with
zero architectural regressions.

---

## Finding 1 — Worker crash on Redis connection failure (D1)

### Evidence

`weebot/infrastructure/queue/redis_task_queue.py:148-149` — `_ensure_group()` is
called **outside** the `while not self._closed` loop's `try/except` block.  If
Redis is unreachable when `dequeue()` is first called, `xgroup_create` inside
`_ensure_group()` raises `redis.exceptions.ConnectionError`.  This propagates
uncaught through `TaskRunner._worker()` at `task_runner.py:68`, which only
handles `asyncio.CancelledError`.  The worker task crashes, halting all
background session processing.  [VERIFIED-STATIC]

### Violated Property

`dequeue()` contract: must either block, return an item, or return `None` —
never crash the caller with an unhandled exception.

### Trigger Condition

Redis server unreachable at the moment `dequeue()` is first called by the
worker.  The `_ensure_group()` call at line 149 raises before the guarded
`while` loop is entered.

### Severity

**MEDIUM** — reachability-adjusted.  The `RedisTaskQueue` is only active when
`WEEBOT_QUEUE_BACKEND=redis`, which defaults to `"memory"`.  When active,
the crash takes down the entire background task runner.  Self-healing is
impossible because the worker exits permanently.

### Architectural Impact

None.  The fix moves an I/O call from an unguarded preamble into an existing
error-handling scope.  No new dependencies, no interface changes, no
behavioral change to existing callers.  `_ensure_group()` is proven
idempotent by the BUSYGROUP catch at `redis_task_queue.py:129-131` — calling
it on every loop iteration is safe.

### Fix

**File:** `weebot/infrastructure/queue/redis_task_queue.py`

Move the `await self._ensure_group()` call from line 149 (outside the while
loop) into the `try:` block at line 152 (inside the loop).  The existing
`except Exception` handler at line 157 already logs and retries — it now
covers `_ensure_group` failures alongside `xreadgroup` failures.

```diff
     async def dequeue(self) -> QueuedSession | None:
         r = await self._get_redis()
-        await self._ensure_group()

         while not self._closed:
             try:
+                await self._ensure_group()
                 result = await r.xreadgroup(
```

### Risk

**Low.**  `xgroup_create` with `mkstream=True` and an existing group is
idempotent — Redis returns `BUSYGROUP` which is caught and ignored at line
129-131.  No other callers depend on the order of `_ensure_group` relative
to the loop.

### Verification

- [ ] [PENDING] Unit test: `RedisTaskQueue` with `redis_url="redis://down-host:9999/0"` → `dequeue()` returns `None` after close, does not raise
- [ ] [PENDING] Integration test: start TaskRunner with Redis, stop Redis, verify worker doesn't crash
- [ ] [PENDING] `lint-imports` — 6 contracts, all kept
- [ ] [PENDING] Existing test suite: 15 tests pass

---

## Finding 2 — Trace span leak on early return (D2)

### Evidence

`weebot/application/flows/plan_act_flow.py:541-551` creates `_run_span` via
`self._tracing_port.start_span("plan_act_iteration")`.  The span is ended at
line 984: `if _run_span is not None: _run_span.end()`.  Two `return`
statements at lines 656 (CompletedState transition from termination
condition) and 716 (PlanStuckError → ErrorEvent yield → return) exit the
generator **before** reaching the cleanup code.  The root trace span is never
ended — the OTEL collector sees a permanently open span.  [VERIFIED-STATIC]

### Violated Property

Span lifecycle invariant: every span created by `start_span()` must be ended
by `.end()`.  Leaving a root span open produces incomplete trace trees.

### Trigger Condition

Plan terminates via the early `return` paths: (a) a `TerminationCondition`
fires and transitions to `CompletedState` at line 656, or (b) `PlanStuckError`
is caught and the flow terminates at line 716.

### Severity

**LOW** — reachability-adjusted.  Tracing is gated behind
`WEEBOT_OTEL_TRACING=true` (default OFF).  The leak is **bounded** — at most
one span per early-terminated flow, not unbounded.  The OTEL collector
eventually expires orphaned spans via its configurable timeout.  The
operational impact is incomplete traces, not memory exhaustion.

### Architectural Impact

None.  The fix adds cleanup on existing control-flow paths.  No new method
calls, no interface changes, no dependency changes.  The `_run_span is not
None` guard already exists at the end-of-method cleanup site — the fix
replicates that same guard on the early-return paths.

### Fix

**File:** `weebot/application/flows/plan_act_flow.py`

Add `if _run_span is not None: _run_span.end()` immediately before each
early `return`:

1. **Before line 657** — `self.set_state(CompletedState(...)); return`
2. **Before line 717** — `return  # terminate the flow gracefully`

```diff
@@ -653,6 +653,8 @@
                     if _result.should_terminate:
                         self._log.info("Termination condition met: %s", _result.reason)
                         from weebot.application.flows.states.completed import CompletedState
+                        if _run_span is not None:
+                            _run_span.end()
                         self.set_state(CompletedState(termination_reason=_result.reason))
                         return

@@ -713,6 +715,8 @@
                         "PLAN_STUCK",
                     ),
                 )
+                if _run_span is not None:
+                    _run_span.end()
                 return  # terminate the flow gracefully
```

### Risk

**Low.**  The existing `.end()` at line 984 still fires for the normal
(non-early-return) path.  No double-end is possible because early `return`
statements exit the generator before reaching line 984.  The `_run_span`
guard is identical to the one already present at the method's end.

### Verification

- [ ] [PENDING] Unit test: `PlanActFlow` with mocked tracing port and `PlanStuckError` → all spans ended after generator exit
- [ ] [PENDING] Integration test: run a flow with tracing enabled, assert no open spans
- [ ] [PENDING] `lint-imports` — 6 contracts, all kept
- [ ] [PENDING] Existing test suite: 15 tests pass

---

## Finding 3 — Silent state-repo failure during FAILED write (D3)

### Evidence

`weebot/application/services/task_runner.py:173-175` — After all retries are
exhausted, `_run_flow` writes:

```python
session = session.set_status(SessionStatus.FAILED)
await self._state_repo.save_session(session)
self._failed_sessions[session_id] = self._max_session_retries
```

If `save_session()` raises (e.g., SQLite disk full, connection pool
exhausted), the exception propagates from the `except Exception` handler into
the `finally` block.  The session's status is never persisted as FAILED, and
`_failed_sessions` is never populated.  The session remains in RUNNING state
in the database forever — preventing any retry via `rerun_failed_session()`
(which requires `status == SessionStatus.FAILED` at line 297) and appearing
permanently active.  [HYPOTHESIS — depends on disk state]

### Violated Property

State machine invariant: a session that exhausts all retries must transition
to FAILED and enter the dead-letter queue.  If the state write fails, this
transition is silently lost — the session becomes unmanageable.

### Trigger Condition

SQLite write failure (disk full, pool exhaustion, file permission change)
coinciding with the final `save_session()` call after all retries are
consumed.

### Severity

**MEDIUM** — reachability-adjusted.  Requires a double failure: the flow
crashes (retries exhausted) AND the state repo is unavailable.  When it
fires, the session is orphaned — neither retryable nor marked as failed.

### Architectural Impact

None.  The fix adds error handling on an existing write path.  No interface
changes, no new dependencies.  The port contract (`StateRepositoryPort`)
already defines `save_session()` as async with no return value guarantee
beyond "writes or raises."

### Fix

**File:** `weebot/application/services/task_runner.py`

Wrap the FAILED write and dead-letter registration in a try/except that
logs the double-failure and ensures the session is at least marked in-memory
as failed so `list_failed_sessions()` returns it.

```diff
@@ -171,9 +171,18 @@
                 if reloaded:
                     await self._start_direct(reloaded, factory)
                     return
-            session = session.set_status(SessionStatus.FAILED)
-            await self._state_repo.save_session(session)
-            self._failed_sessions[session_id] = self._max_session_retries
+            try:
+                session = session.set_status(SessionStatus.FAILED)
+                await self._state_repo.save_session(session)
+            except Exception as persist_exc:
+                logger.error(
+                    "Double failure: state repo write failed after flow crash "
+                    "for session %s — session may be orphaned in RUNNING state. "
+                    "Error: %s", session_id, persist_exc,
+                )
+                # Register in dead-letter anyway so operators know it failed
+            finally:
+                self._failed_sessions[session_id] = self._max_session_retries
```

### Risk

**Low.**  The existing behavior (uncaught exception) is strictly worse — the
session is silently lost.  The fix ensures: (a) the error is logged with
full context, (b) the dead-letter queue is always populated regardless of
write success, and (c) the exception no longer propagates into the `finally`
block, preventing the `flow.teardown()` and metrics cleanup from being
skipped.

### Verification

- [ ] [PENDING] Unit test: `TaskRunner` with `state_repo.save_session` mocked to raise → `list_failed_sessions()` still contains the session
- [ ] [PENDING] Unit test: error log emitted with session ID
- [ ] [PENDING] `lint-imports` — 6 contracts, all kept
- [ ] [PENDING] Existing test suite: 15 tests pass

---

## Migration Sequencing

```
D1 (redis_task_queue.py)  ──→  D3 (task_runner.py)
D2 (plan_act_flow.py)     ──→  (parallel — independent files)

All three touch different files with no ordering dependency.
```

---

## Risk Matrix

| Finding | Risk | Rollback | Rollback time |
|---|---|---|---|
| D1 — Worker crash | Low | `git revert` | 1 min |
| D2 — Span leak | Low | `git revert` | 1 min |
| D3 — Silent FAILED write | Low | `git revert` | 1 min |

---

## Score Impact

None — these are correctness fixes, not architectural improvements.
The architecture score remains at **9.6**.  Clean claim: the audited
surface has zero remaining VERIFIED-STATIC defects after all three
fixes are applied.

---

## Appendix — Full Evidence Index

| Finding | EGFV | Source |
|---|---|---|
| `_ensure_group()` outside try/except in `dequeue()` | [VERIFIED-STATIC] | `read_file weebot/infrastructure/queue/redis_task_queue.py:145-160` |
| `_worker()` only catches `CancelledError` on `dequeue()` | [VERIFIED-STATIC] | `read_file weebot/application/services/task_runner.py:67-71` |
| Early `return` at line 656 bypasses `_run_span.end()` | [VERIFIED-STATIC] | `read_file weebot/application/flows/plan_act_flow.py:650-660` |
| Early `return` at line 716 bypasses `_run_span.end()` | [VERIFIED-STATIC] | `read_file weebot/application/flows/plan_act_flow.py:710-720` |
| `_run_span.end()` at line 984 unreachable from early returns | [VERIFIED-STATIC] | `read_file weebot/application/flows/plan_act_flow.py:980-985` |
| FAILED `save_session()` can raise inside `except` handler | [HYPOTHESIS] | `read_file weebot/application/services/task_runner.py:170-176` |
| `rerun_failed_session()` requires `SessionStatus.FAILED` | [VERIFIED-STATIC] | `read_file weebot/application/services/task_runner.py:295-298` |
