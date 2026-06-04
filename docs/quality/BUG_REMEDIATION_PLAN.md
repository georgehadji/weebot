# Bug Remediation Plan — Weebot Codebase

**Author:** Architecture Audit — Safety-Focused Phase
**Date:** 2026-07-06
**Prerequisite:** Architectural Remediation (Phases 1–4) complete. Codebase at commit `a816233`.
**Status:** Plan — pending execution

---

## Overview

35 latent bugs identified via systematic static analysis across 5 categories:
- **5** Injection/Taint (B1–B5)
- **8** Resource/Memory (B6–B13)
- **7** Concurrency/Race (B14–B20)
- **9** Logic/Edge Cases (B21–B29)
- **3** TOCTOU (B30–B31)
- **3** Missing Error Handling (B32–B34)

| Severity | Count | Fix Priority |
|----------|-------|-------------|
| HIGH | 5 | **Phase 1 (critical)** |
| MEDIUM | 11 | **Phase 2 (within sprint)** |
| LOW | 19 | **Phase 3 (backlog queue)** |

---

## Sequencing Strategy

Bugs are ordered by dependency chain and blast radius:

```
Phase 1: Core safety (code injection, credential leak, stack trace, lock contention, error recovery)
    ↓
Phase 2: Correctness (TOCTOU, atomic writes, connection pool, timeouts, rate limits, confirmation UX)
    ↓
Phase 3: Hygiene (traceback loss, generator leaks, inconsistent clocks, dead code, mixed timezones)
```

Each phase must complete fully before the next begins — some Phase 1 bug fixes may affect Phase 2 code paths.

---

## Phase 1 — Critical Safety (5 bugs)

### Bug B21 — Mediator Stack Trace Leak
- **File:** `weebot/application/cqrs/mediator.py`
- **Lines:** 127–135 (command), 169–176 (query)
- **Fix:** Replace `raise HandlerNotRegisteredError(...)` with `return CommandResult.fail(error=..., error_code="HANDLER_NOT_REGISTERED")`
- **Risk:** **Low** — no existing code catches `HandlerNotRegisteredError` specifically; callers already check `result.success`
- **Test:** Add `test_send_unknown_command_returns_fail_not_raise`
- **Dependencies:** None — pure refactor in mediator

### Bug B1 — Python Code Injection (No Resource Limits)
- **File:** `weebot/tools/python_tool.py`
- **Lines:** 101–107 (execute method)
- **Fix:** Pass `memory_limit_mb=256` to `self._sandbox.execute_python()` call
- **Risk:** **Low** — adding a kwarg that the SandboxPort already supports; only affects PythonTool
- **Test:** Update `test_python_tool.py` to verify `memory_limit_mb` is passed to sandbox
- **Dependencies:** Requires `execute_python` method in `SandboxPort` to accept `memory_limit_mb` — verify `NativeWindowsSandbox` signature first

### Bug B2 — Credential Leak in LLM Adapter
- **File:** `weebot/infrastructure/adapters/llm/resilient_adapter.py`
- **Lines:** 197 (re-raise), 206 (re-raise), all error message propagation paths
- **Fix:** Add `_sanitize_error()` static method; call on every exception before logging or re-raising; redact `api_key=`, `sk-*`, `token=` patterns
- **Risk:** **Low** — error handling only; sanitized message is less useful for debugging but prevents key leaks
- **Test:** Parametrized test for credential patterns
- **Dependencies:** None — pure utility addition

### Bug B6/B7/B32 — `_emit` Lock Contention & Error Recovery (combined)
- **File:** `weebot/application/flows/plan_act_flow.py`
- **Lines:** 92–115 (`_emit` method)
- **Fix:**
  1. Narrow `_emit_lock` to only the `save_session()` call (DB write)
  2. Move in-memory mutation and event bus publish outside the lock
  3. Wrap `save_session()` in try/except — log error, continue (SavePolicyBehavior retries on next command)
- **Risk:** **Medium** — changes the locking semantics of the hottest code path in the system. Requires careful testing of concurrent flow execution.
- **Test:** `test_emit_does_not_crash_on_db_failure` with `FailingRepo` mock
- **Dependencies:** B11 (generator leak) may interact — test both together

---

## Phase 2 — Correctness (11 bugs)

### Bug B3 — Path Traversal via Workspace-Internal Symlinks
- **File:** `weebot/tools/file_editor.py`
- **Lines:** 131–144 (PathValidator), 157–159 (`_view` uses `is_dir()` + `iterdir()`)
- **Fix:** After `resolve()`, check if any component of the resolved path is a symlink. If yes, reject the access. Alternative: use `os.stat(path).st_ino != os.lstat(path).st_ino` to detect symlink-following.
- **Risk:** **Low** — symlink detection is a well-understood problem with known APIs
- **Test:** Create symlink in workspace pointing to `/etc`, verify `view` rejects it

### Bug B4 — File Extension Bypass on Create
- **File:** `weebot/tools/file_editor.py`
- **Lines:** 134–135 (allow_create logic)
- **Fix:** Enforce `ALLOWED_EXTENSIONS` for all commands, not just read/write. Remove the `allow_create` exception.
- **Risk:** **Low** — `.exe`/`.dll`/`.ps1` create is already blocked by Windows permissions; the extension filter adds defense-in-depth
- **Test:** Verify `create` with `.exe` extension is rejected

### Bug B8 — Zero/Negative Timeout Bypass
- **File:** `weebot/tools/bash_tool.py`
- **Lines:** 225–230 (timeout calculation)
- **Fix:** Add `effective_timeout = max(effective_timeout, 1.0)` after float coercion. Add default ceiling `min(effective_timeout, 300.0)` when `set_config()` was never called.
- **Risk:** **Low** — pure clamping logic
- **Test:** Verify timeout=0 is clamped to 1.0, timeout=-5 is clamped to 1.0

### Bug B9 — Non-Atomic Write (File Editor)
- **File:** `weebot/tools/file_editor.py`
- **Lines:** 181–195 (`_str_replace`), insert method
- **Fix:** Write to temp file (`path.with_suffix('.tmp')`), then `Path.replace()` (atomic on same filesystem)
- **Risk:** **Low** — standard atomic-write pattern
- **Test:** Verify no `.tmp` leftover; verify file content is correct after write

### Bug B10 — Missing Memory Limit on Python Tool
- **File:** `weebot/tools/python_tool.py` — same as B1
- **Fix:** Combined with B1 fix above — single change
- **Note:** Already covered in Phase 1 B1 fix

### Bug B14 — Mediator Pipeline Behavior Race
- **File:** `weebot/application/cqrs/mediator.py`
- **Lines:** 93 (`add_pipeline_behavior`), 107–115 (`_execute_with_pipeline` reads list by index)
- **Fix:** Add docstring: "NOT thread-safe — call at startup only." Document the invariant that behaviors are registered before `send()`/`query()` are ever called (this is already true at the DI level — `build_mediator()` adds behaviors before returning the mediator instance).
- **Risk:** **Low** — documentation change only; no behavioral change
- **Test:** No code change to test — verify the invariant by reviewing `di.py:build_mediator()` sequence

### Bug B15 — Circuit Breaker TOCTOU Race
- **File:** `weebot/core/circuit_breaker.py`
- **Lines:** 119–127 (dirty pre-check), 129–162 (locked check)
- **Fix:** Move the OPEN→cooldown→HALF_OPEN transition entirely under the lock. Remove the dirty pre-check shortcut. Accept the slightly higher latency for correctness.
- **Risk:** **Medium** — changes circuit breaker behavior under high load. The lock is now acquired on every call, not just on OPEN→HALF_OPEN transitions.
- **Test:** `test_circuit_breaker_no_double_probe` — two concurrent callers produce exactly one probe

### Bug B16 — Transaction State Corruption on Commit Failure
- **File:** `weebot/infrastructure/persistence/connection_pool.py`
- **Lines:** 160–169 (execute_write try/except)
- **Fix:** After rollback, close and reopen the write connection to ensure a clean slate for the next transaction.
- **Risk:** **Low** — only triggers on commit failure (rare); reopening the connection adds ~5ms latency on the failure path
- **Test:** `test_write_connection_recovers_after_commit_failure`

### Bug B17 — Deadlock Risk (Connection Pool)
- **File:** `weebot/infrastructure/persistence/connection_pool.py`
- **Lines:** 88–92 (lock + semaphore + queue)
- **Fix:** Add documentation comment: "Never acquire _write_lock inside a read context, or vice versa."
- **Risk:** **Low** — documentation only; no behavioral change
- **Test:** Review all callers for nested lock acquisition

### Bug B22 — Silent Denial Instead of Confirmation
- **File:** `weebot/tools/bash_tool.py`
- **Lines:** 247–257 (requires_confirmation branch)
- **Fix:** Clarify error message from "Command requires user confirmation" to "Command blocked — requires user confirmation: {hint}". No behavioral change — the confirmation channel doesn't exist yet.
- **Risk:** **Low** — error message change only
- **Test:** Verify error message format in test

### Bug B23 — Retry Amplification on Rate Limit
- **File:** `weebot/infrastructure/adapters/llm/resilient_adapter.py`
- **Lines:** 226–230 (`_is_retryable_error`)
- **Fix:** Remove `ErrorCategory.RATE_LIMIT` from the retryable set. Rate-limited requests will fail-fast to circuit breaker, which cascades to the next provider.
- **Risk:** **Medium** — changes the retry behavior for rate-limited providers. Verify the circuit breaker opens correctly and cascade fallback still works.
- **Test:** Parametrized test verifying RATE_LIMIT → not retryable

---

## Phase 3 — Hygiene (19 bugs)

### Batch A: Traceback & Error Message Quality (4 bugs)

#### B12 — Traceback Loss in ToolExecution
- **File:** `weebot/application/models/tool_collection.py`
- **Lines:** 67–80
- **Fix:** Add `logger.exception("Tool %s failed", tool_name)` before returning `error_result`
- **Risk:** **Low** — adds logging, no behavioral change

#### B13 — f-string in Logger Debug (Performance)
- **File:** `weebot/infrastructure/adapters/llm/resilient_adapter.py`
- **Lines:** 107–111
- **Fix:** Change `logger.debug(f"...")` to `logger.debug("%s", value)` — lazy evaluation
- **Risk:** **Low** — formatting change only

#### B25 — Dead Code Verification (bash_tool)
- **File:** `weebot/tools/bash_tool.py`
- **Fix:** Remove `_verify_command_execution` method and all `_state_verifier` references (dead code from remediation step-7a)
- **Risk:** **Low** — removing code that is never reached

#### B29 — Missing Platform Check (voice_output)
- **File:** `weebot/tools/voice_output_tool.py`
- **Fix:** Add `import sys; if sys.platform != "win32": return ToolResult.error_result("..." )` guard at top of `execute()`
- **Risk:** **Low** — returns clean error instead of crashing

### Batch B: Generator & State Leaks (3 bugs)

#### B11 — Async Generator Leak
- **File:** `weebot/application/flows/plan_act_flow.py`
- **Lines:** 168–169
- **Fix:** Add `finally:` block that tracks and closes the inner state generator if needed
- **Risk:** **Low** — minor behavioral change; Python GC already handles this in most cases

#### B20 — Stale plan_critique
- **File:** `weebot/application/flows/plan_act_flow.py`, `states/critiquing.py`
- **Fix:** Reset `self._plan_critique = None` in CritiquingState's `finally` or on failure
- **Risk:** **Low** — minor state cleanup

#### B34 — Background Task Leak in Sandbox
- **File:** `weebot/infrastructure/sandbox/native_windows.py`
- **Lines:** 194–197
- **Fix:** Add `self._stop_event.set()` in the `finally` block of the sandbox executor
- **Risk:** **Low** — prevents orphan monitor threads

### Batch C: Time & State Inconsistency (3 bugs)

#### B18 — Non-Monotonic Clock (time.time)
- **File:** `weebot/application/flows/states/executing.py`
- **Lines:** 69
- **Fix:** Replace `time.time()` with `time.monotonic()`
- **Risk:** **Low** — one-line replacement

#### B19 — Double-Emit in CompletedState
- **File:** `weebot/application/flows/states/completed.py`
- **Lines:** 24–25
- **Fix:** Remove the separate `yield completed` — keep only `context._emit(completed)` which already publishes
- **Risk:** **Low** — ensures single event delivery

#### B24 — Timezone Inconsistency
- **File:** `weebot/domain/models/event.py` — all `Field(default_factory=...)` using datetime
- **Fix:** Standardize all datetime factories on `datetime.now(timezone.utc)` — check every event class
- **Risk:** **Low** — one-line replacements across ~15 event classes

### Batch D: Logic & UX (5 bugs)

#### B3 (? B5 directory listing — already covered in B3 fix above)
#### B26 — Approval Bypass (obfuscated Python)
- **File:** `weebot/tools/python_tool.py`
- **Lines:** 86–90
- **Fix:** Add `__import__` and `sys.modules` to the DENY pattern list in `ExecApprovalPolicy`
- **Risk:** **Low** — expands deny regex

#### B27 — Inconsistent ToolResult State
- **File:** `weebot/tools/base.py`
- **Lines:** 42–46 (`__post_init__`)
- **Fix:** Change `success` field to `field(init=False)` — computed from `error` only. Prevents direct `success=True` misuse.
- **Risk:** **Medium** — changes the `ToolResult` constructor API. Easier fix: add `@classmethod` named constructors and make `__init__` private.

#### B28 — Duplicate Query Registration Silent Overwrite
- **File:** `weebot/application/cqrs/mediator.py`
- **Lines:** 62–68 (command raise), query registration (no raise)
- **Fix:** Add same `ValueError` raise for duplicate query registration
- **Risk:** **Low** — adding a guard, not changing behavior

#### B30/B31 — TOCTOU Races
- **File:** `weebot/tools/file_editor.py:144-146`, `weebot/tools/bash_tool.py:225-230`
- **Fix:** B30: Re-resolve path after `relative_to` check. B31: Capture config snapshot at method entry.
- **Risk:** **Low** — narrow windows, both difficult to exploit in practice

---

## Implementation Order (By File)

To minimize rebase conflicts and test churn:

| Batch | Files | Bugs Covered | Est. Effort |
|-------|-------|-------------|-------------|
| 1 | `mediator.py` | B21, B14, B28 | 30 min |
| 2 | `bash_tool.py` | B8, B22, B25 | 45 min |
| 3 | `python_tool.py` | B1, B10, B26 | 30 min |
| 4 | `resilient_adapter.py` | B2, B23, B13 | 45 min |
| 5 | `plan_act_flow.py` | B6, B7, B32, B11, B20 | 60 min |
| 6 | `file_editor.py` | B3, B4, B9, B30 | 45 min |
| 7 | `connection_pool.py` | B16, B17 | 30 min |
| 8 | `circuit_breaker.py` | B15 | 30 min |
| 9 | `native_windows.py` | B34 | 15 min |
| 10 | `event_bus.py` | B33 | 15 min |
| 11 | `tool_collection.py` | B12 | 15 min |
| 12 | `states/completed.py` | B19 | 15 min |
| 13 | `states/executing.py` | B18 | 15 min |
| 14 | `base.py` | B27 | 20 min |
| 15 | `event.py` | B24 | 30 min |
| 16 | `voice_output_tool.py` | B29 | 15 min |
| 17 | `states/critiquing.py` | B20 | 15 min |

**Total estimated effort:** ~8 hours (including test writing and verification runs)

---

## Verification Strategy

After each batch:

```bash
# 1. Run the specific regression test for this batch
pytest tests/unit/<test_file> -v --tb=short -x

# 2. Run all architecture fitness tests
pytest tests/unit/test_architecture_fitness.py -v --tb=short

# 3. Run all tests in affected directories
pytest tests/unit/tools/ tests/unit/application/ -v --tb=short

# 4. Full test suite (after all batches)
pytest tests/unit/ -v --tb=short -x
```

### Acceptance Criteria
- [ ] All new regression tests pass
- [ ] All 17 existing architecture fitness tests pass
- [ ] Pipeline behaviors still fire (`test_every_command_has_handler`)
- [ ] `test_interfaces_no_infrastructure_adapter_imports` still passes
- [ ] No new import-linter violations

---

## Risk Matrix

| Bug | Risk of Fix | Blast Radius | Mitigation |
|-----|------------|-------------|------------|
| B6/B7/B32 (lock narrowing) | **Medium** | Every flow execution | Test with concurrent flows; verify no event ordering issues |
| B15 (circuit breaker lock) | **Medium** | All LLM calls | Performance test: verify lock acquisition doesn't bottleneck |
| B23 (rate limit no-retry) | **Medium** | All LLM calls | Verify cascade fallback works correctly after fail-fast |
| B27 (ToolResult constructor) | **Medium** | Every tool | Add deprecation path: keep old constructor, add factory methods |
| All others | **Low** | Single module | Standard regression test coverage |

---

## Bug Fix Package Index

Detailed fix packages (diff + test + verification checklist) for all HIGH/MEDIUM bugs (16) are provided in the Phase 2 audit. LOW bugs (19) have one-line fix descriptions — expand to full packages at execution time.

See commit `a816233` for the codebase state before bug fixes are applied.
