# Architecture Excellence Plan — Target > 8.5 / 10

**Baseline Score:** 6.8 / 10 (June 2026 Audit)  
**Target Score:** ≥ 8.5 / 10  
**Overall Delta:** +1.7 points minimum  
**Estimated Effort:** 16–20 person-days

---

## Score Trajectory

| Dimension | Current | Target | Delta | Criticality |
|-----------|---------|--------|-------|-------------|
| Domain Purity | 10 / 10 | 10 / 10 | — | Preserve ✅ |
| CQRS Enforcement | 7 / 10 | 9 / 10 | +2 | Core pattern |
| Dependency Direction | 6 / 10 | 9 / 10 | +3 | Architectural integrity |
| Security Boundary Integrity | 5 / 10 | 8 / 10 | +3 | Production safety |
| Observability | 2 / 10 | 8 / 10 | +6 | Operability |
| Test Architecture | 8 / 10 | 9 / 10 | +1 | Confidence |
| DI / IoC Consistency | 5 / 10 | 9 / 10 | +4 | Maintainability |
| State Management | 3 / 10 | 9 / 10 | +6 | Data integrity |
| Async Hygiene | 5 / 10 | 8 / 10 | +3 | Runtime stability |
| Error Handling | 5 / 10 | 8 / 10 | +3 | Production resilience |
| **Weighted Average** | **6.8** | **8.7** | **+1.9** | |

---

## Phase A — Foundation (Week 1, ~4 days)

> Fix the CRITICAL and HIGH findings that are blocking operational trust.

### A.1 Persistence Policy: Uniform Save-at-Emit (1 day)

**From:** 3/10 — `PlanActFlow._emit()` never persists; `CompletedState` doesn't finalize; `ChatFlow._emit()` does — inconsistent.

**To:** 8/10 — Every flow persists at the boundary via a shared policy.

| Step | File | Action |
|------|------|--------|
| A.1.1 | `flows/plan_act_flow.py:112-114` | Add `await self._state_repo.save_session(self._session)` after `_emit()` |
| A.1.2 | `flows/plan_act_flow.py:__init__` | Accept and store `state_repo: Optional[StateRepositoryPort]` parameter |
| A.1.3 | `di.py` (all flow factory sites) | Pass `state_repo=self.get(StateRepositoryPort)` when creating flows |
| A.1.4 | `flows/states/completed.py:25` | Call `context._state_repo.save_session()` after setting COMPLETED status |
| A.1.5 | Extract `SavePolicyBehavior` | IPipelineBehavior that auto-saves after every command handler completes |
| A.1.6 | `tests/unit/test_persistence.py` | New test: create flow → emit events → verify persisted |

**Verification:**
```bash
grep -rn "save_session" weebot/application/flows/ --include="*.py" | wc -l
# Expected: ≥ 2 (PlanActFlow._emit + CompletedState)
pytest tests/unit/test_persistence.py -v
```

### A.2 PowerShellTool SandboxPort Security Fix (0.5 day)

**From:** 5/10 — SandboxPort path bypasses ALL security validators.

**To:** 8/10 — Both the SandboxPort and fallback paths go through identical security gates.

| Step | File | Action |
|------|------|--------|
| A.2.1 | `tools/powershell_tool.py:196` | Call `self._inner._validate_no_encoded_commands(command)` before SandboxPort |
| A.2.2 | `tools/powershell_tool.py:196` | Call `self._inner._validate_path_safety(command)` before SandboxPort |
| A.2.3 | `tools/powershell_tool.py` | Add `ExecApprovalPolicy` import and gate before both execution paths |
| A.2.4 | `tests/unit/test_powershell_security.py` | New test: dangerous commands rejected regardless of SandboxPort injection |

**Verification:**
```python
# Test: SandboxPort path must block encoded commands
tool = PowerShellBaseTool()
tool.set_sandbox_port(mock_sandbox)
result = await tool.execute("-e SGVscA==")  # encoded payload
assert "Security Error" in result.error
```

### A.3 Prometheus Metrics: Wire or Die (1 day)

**From:** 2/10 — All 7 metrics defined but zero `.inc()` calls.

**To:** 8/10 — Every key code path increments the right metric.

**Decision:** **Wire them.** The metrics infrastructure is already there; the delta is ~25 lines of instrumentation.

| Step | File | Instrument |
|------|------|------------|
| A.3.1 | `adapters/llm/resilient_adapter.py` | `llm_calls_total.labels(model, provider, status).inc()` after each API call |
| A.3.2 | `adapters/llm/resilient_adapter.py` | `llm_call_duration_seconds.labels(model, provider).observe(duration)` |
| A.3.3 | `tools/base.py` (ToolResult) or `tool_registry.py` | `tool_calls_total.labels(tool_name, success).inc()` after each tool execution |
| A.3.4 | `flows/plan_act_flow.py` (state transition) | `flow_step_duration_seconds.labels(flow_type, state).observe(duration)` |
| A.3.5 | `services/task_runner.py` | `session_active.inc()` on start, `.dec()` on finish; `session_total.inc()` on create |
| A.3.6 | `infrastructure/event_bus.py` | `events_published_total.labels(event_type).inc()` in `publish()` |
| A.3.7 | `interfaces/web/main.py` or global handler | `exceptions_total.labels(exception_type).inc()` in exception handler |

**Verification:** `curl http://localhost:8000/api/prometheus` returns non-zero counters after 1 session.

### A.4 Error Boundaries: Global Exception Handlers (1 day)

**From:** 5/10 — No `@app.exception_handler`; CLI crashes with raw traceback.

**To:** 8/10 — Structured errors at every external boundary.

| Step | File | Action |
|------|------|--------|
| A.4.1 | `interfaces/web/main.py` | Add `@app.exception_handler(Exception)` → returns structured JSON with error code |
| A.4.2 | `interfaces/web/main.py` | Add `@app.exception_handler(WEEBOT_ERROR_CLASS)` → maps `WeebotError` codes to HTTP statuses |
| A.4.3 | `cli/main.py` | Wrap entire `cli()` body in try/except → structured error message to stderr |
| A.4.4 | `interfaces/web/routers/health.py` | Replace per-component try/except with a unified health check returning `PartialResult` objects |

**Verification:**
```bash
curl -H "X-API-Key: bad" http://localhost:8000/api/sessions
# Expected: 401 { "error_code": "UNAUTHORIZED", "detail": "..." }
```

---

## Phase B — Consolidation (Week 2, ~4 days)

> Fix the structural drift between the declared architecture and the implemented reality.

### B.1 CLI DI Migration: Composition Root Restoration (1 day)

**From:** 5/10 — CLI constructs adapters in 6 separate places; `run.py` has its own wiring.

**To:** 9/10 — CLI resolves everything through `Container.get()`.

| Step | File | Action |
|------|------|--------|
| B.1.1 | `cli/main.py:719+` | Replace all `SQLiteStateRepository(db_path=...)` with `container.get(StateRepositoryPort)` |
| B.1.2 | `cli/main.py` | Initialize `Container()` once, call `configure_defaults()`, pass container to subcommands |
| B.1.3 | `run.py:101,126` | Replace direct construction with `Container.get()` |
| B.1.4 | `cli/main.py` | Split monolithic `cli()` function (683 lines) into `register_commands(app, container)` pattern |
| B.1.5 | `tests/unit/test_cli_di.py` | New test: verify every `SQLiteStateRepository()` construction outside `di.py` is gone |

**Verification:**
```bash
grep -rn "SQLiteStateRepository()" weebot/ cli/ run.py --include="*.py" | grep -v "di.py" | grep -v "test_"
# Expected: 0 results
```

### B.2 Dead Code Removal + Bash Guard Integration (0.5 day)

**From:** Security inconsistency with `bash_guard.py` orphaned.

**To:** One clear security pipeline — either `bash_guard.py` is wired or removed.

| Step | File | Action |
|------|------|--------|
| B.2.1 | `tools/bash_tool.py` | Wire `bash_guard.BashGuard.check_command()` as an additional security layer, OR — |
| B.2.2 | `core/bash_guard.py` | Delete it (300 lines of dead code with no callers) if the existing `bash_security.py` is sufficient |
| B.2.3 | `tools/python_tool.py` | Add `ExecApprovalPolicy` to the SandboxPort path (currently only on fallback) |
| B.2.4 | `core/approval_policy.py:63-68` | Log a warning when a regex fails to compile instead of silently skipping |

### B.3 CQRS Escape Elimination (1 day)

**From:** 7/10 — SummarizingState bypasses mediator; fallback paths skip pipeline behaviors.

**To:** 9/10 — All mutations through mediator; fallback deprecated.

| Step | File | Action |
|------|------|--------|
| B.3.1 | Create `SummarizeCommand` + `SummarizeHandler` | `cqrs/commands.py` + handler in `handlers.py` — delegate to `ExecutorAgent.summarize()` |
| B.3.2 | `states/summarizing.py:22` | Replace `context._executor.summarize()` with `mediator.send(SummarizeCommand(...))` |
| B.3.3 | `states/planning.py:59-63` | Add `DeprecationWarning` on fallback path; log whenever mediator is None |
| B.3.4 | `states/executing.py:104-106` | Same — deprecation warning on fallback |
| B.3.5 | `states/updating.py:77-79` | Same — deprecation warning on fallback |
| B.3.6 | Register orphan commands | `AskUserCommand` + `AnswerUserCommand` → add handlers or delete from `commands.py` |

**Verification:**
```python
# Fitness test assertion
for state_file in flow_state_files:
    assert "context._planner.create_plan" not in state_file.read_text(), \
        f"{state_file} has direct agent call bypassing mediator"
```

### B.4 `.importlinter` Contract Fix (0.25 day)

| Step | File | Action |
|------|------|--------|
| B.4.1 | `.importlinter` | Rewrite `flat-file-elimination` to use `indirect` type or split into per-layer contracts |
| B.4.2 | `Makefile` | Verify `make lint-imports` succeeds |

---

## Phase C — Hardening (Week 3, ~4 days)

> Elevate every dimension that's holding the score below 8.

### C.1 Async Hygiene: Eliminate Blocking Calls (1 day)

**From:** 5/10 — `subprocess.run()` in PowerShellTool, `time.sleep()` in behavior_tracker.

**To:** 8/10 — Zero blocking calls in async functions.

| Step | File | Action |
|------|------|--------|
| C.1.1 | `tools/powershell_tool.py:131` | Replace `subprocess.run()` with `asyncio.create_subprocess_exec()` |
| C.1.2 | `core/behavior_tracker.py:542` | Replace `time.sleep(1)` with `await asyncio.sleep(1)` (or remove the sleep entirely) |
| C.1.3 | `core/behavior_tracker.py:156,241,319` | Replace `subprocess.run(["git", ...])` with `asyncio.create_subprocess_exec()` |
| C.1.4 | `tools/design_system_tool.py:73,96,108` | Replace `subprocess.run()` with async subprocess |
| C.1.5 | `tests/unit/test_async_hygiene.py` | New fitness test: AST scan for `subprocess.run` and `time.sleep` in async functions |

### C.2 Settings Decoupling (1 day)

**From:** 5/10 — `WeebotSettings` imported by 12+ files across all layers.

**To:** 8/10 — Tool config arrives via constructor injection; only `di.py` and `config/` import settings.

| Step | File | Action |
|------|------|--------|
| C.2.1 | Define `ToolConfig` dataclass | `weebot/config/tool_config.py` — `bash_timeout`, `python_timeout`, `sandbox_max_output_bytes` |
| C.2.2 | `tools/bash_tool.py` | Accept `config: ToolConfig` via constructor instead of calling `_get_settings()` |
| C.2.3 | `tools/python_tool.py` | Same — accept `ToolConfig` |
| C.2.4 | `tools/file_editor.py` | Same pattern |
| C.2.5 | `tools/tool_registry.py` | Pass `tool_config` when creating tool instances |
| C.2.6 | `di.py` | Create `ToolConfig` from `WeebotSettings` and inject it |

**Verification:**
```bash
grep -rn "WeebotSettings\|_get_settings" weebot/tools/ --include="*.py" | grep -v "test_"
# Expected: 0 results
```

### C.3 Event Catalog & Dual System Sunset Plan (0.5 day)

| Step | File | Action |
|------|------|--------|
| C.3.1 | `docs/EVENT_CATALOG.md` | Document all 19+ event types with publisher, subscriber, and bridge mapping |
| C.3.2 | `docs/EVENT_BUS_MIGRATION.md` | Document the path to sunset the EventBroker (timeline, checklist) |
| C.3.3 | `infrastructure/events/broker_adapter.py` | Complete the `_convert()` mapping — search for all event type strings in codebase |

### C.4 Handler File Decomposition (0.5 day)

**From:** `handlers.py` is 850 lines (15 handler classes in one file).

**To:** `handlers/` subdirectory with one handler per file.

| Step | Action |
|------|--------|
| C.4.1 | Split `handlers.py` into `handlers/` — `create_plan.py`, `execute_step.py`, `update_plan.py`, etc. |
| C.4.2 | Update `register_default_handlers()` to import from handler files |
| C.4.3 | Ensure existing subdirectory handlers (`skill_edit_handler.py`, etc.) follow same pattern |

---

## Phase D — Validation (Week 4, ~4 days)

> Cement the improvements with automated enforcement.

### D.1 Architecture Fitness Test Expansion (1 day)

**From:** 8/10 — 12 tests, 3 known gaps.

**To:** 9/10 — 20+ tests covering all new rules.

New tests to add:

| Test | Enforces |
|------|----------|
| `test_persistence_at_emit` | Flows with `state_repo` must call `save_session` after `_emit` |
| `test_no_blocking_calls_in_async` | AST scan for `subprocess.run`/`time.sleep` outside sync methods |
| `test_no_settings_import_in_tools` | `WeebotSettings` must not be imported by `weebot/tools/` |
| `test_all_commands_have_pipeline_behaviors` | Every command handler registered with LoggingBehavior+TelemetryBehavior |
| `test_security_gates_before_execution` | Tools must call security validators before SandboxPort/Executor |
| `test_repository_constructed_only_in_di` | AST scan — `SQLiteStateRepository()` only in `di.py` |
| `test_all_event_types_documented` | Every `AgentEvent` subtype must appear in `docs/EVENT_CATALOG.md` |
| `test_global_exception_handlers_registered` | FastAPI app must have at least one `@app.exception_handler` |

### D.2 E2E Persistence Test (1 day)

| Test | Purpose |
|------|---------|
| `test_plan_act_flow_persists_all_events` | Create flow with real SQLite → run 3 steps → verify all events in DB |
| `test_chat_flow_persists_all_events` | Same for ChatFlow |
| `test_completed_status_persisted` | Flow completes → reload session from DB → verify status is COMPLETED |

### D.3 Security Penetration Tests (1 day)

| Test | Attack Vector |
|------|--------------|
| `test_encoded_command_blocked_sandbox_port` | PowerShellTool with SandboxPort: `-enc base64payload` → must be blocked |
| `test_dangerous_command_blocked_sandbox_port` | BashTool with SandboxPort: `rm -rf /` → must be denied |
| `test_path_traversal_blocked_sandbox_port` | PowerShellTool with SandboxPort: `C:\Windows\System32\..\` → must be blocked |
| `test_broken_regex_silent_failure` | `ExecApprovalPolicy` with invalid pattern → must log warning |

### D.4 CI/CD Enforcement (1 day)

| Step | Action |
|------|--------|
| D.4.1 | `.github/workflows/architecture.yml` | Add `make lint-imports` job (blocking PR merge) |
| D.4.2 | `.github/workflows/architecture.yml` | Add `pytest tests/unit/test_architecture_fitness.py -v` (blocking) |
| D.4.3 | `.github/workflows/architecture.yml` | Add `pytest tests/e2e/test_persistence.py -v` (blocking) |
| D.4.4 | `pre-commit` config | Add `make lint-imports` hook to prevent offline violations |

---

## Phase E — Polish (Week 5, ~2 days)

### E.1 God Module Decomposition

| Module | Current Lines | Target | Approach |
|--------|--------------|--------|----------|
| `cli/main.py` | 1,006 | ~200 (main) + 10×80 (commands) | Extract each subcommand into `cli/commands/<name>.py` |
| `state_manager.py` | 641 | 641 + LEGACY header | Already deprecated — no investment. Add sunset date. |
| `handlers.py` | 850 | ~100 (registration only) | Handled in C.4 |

### E.2 telemetry → Prometheus Wire-Up

| Step | File | Action |
|------|------|--------|
| E.2.1 | `behaviors/telemetry.py` | Call `flow_step_duration_seconds.labels().observe()` instead of `logging.info()` |
| E.2.2 | Update `metrics.py` docstring | "Used by: behaviors/telemetry.py, event_bus.py, task_runner.py" |

### E.3 ADR 006–008

| ADR | Decision |
|-----|----------|
| 006 | Persistence policy: save-at-emit with `SavePolicyBehavior` |
| 007 | Settings decoupling: `ToolConfig` per adapter pattern |
| 008 | Event system sunset: EventBroker removal timeline |

---

## Full Sprint Schedule

```
Week 1 ┤ A.1: Persistence Policy (1d)
       ┤ A.2: PowerShellTool Security (0.5d)
       ┤ A.3: Prometheus Wiring (1d)
       ┤ A.4: Error Boundaries (1d)
       ┤ Buffer (0.5d)
       ┤                                    → Score target: ~7.5/10

Week 2 ┤ B.1: CLI DI Migration (1d)
       ┤ B.2: Dead Code + Bash Guard (0.5d)
       ┤ B.3: CQRS Escape Elimination (1d)
       ┤ B.4: importlinter Fix (0.25d)
       ┤ B.5: CQRS hander decomposition (0.5d)
       ┤ Buffer (0.75d)
       ┤                                    → Score target: ~8.0/10

Week 3 ┤ C.1: Async Hygiene (1d)
       ┤ C.2: Settings Decoupling (1d)
       ┤ C.3: Event Catalog (0.5d)
       ┤ C.4: Handler decomposition (0.5d)
       ┤ Buffer (1d)
       ┤                                    → Score target: ~8.3/10

Week 4 ┤ D.1: Fitness Test Expansion (1d)
       ┤ D.2: E2E Persistence Tests (1d)
       ┤ D.3: Security Penetration Tests (1d)
       ┤ D.4: CI/CD Enforcement (1d)
       ┤                                    → Score target: ~8.7/10

Week 5 ┤ E.1: God Module Decomposition (1d)
       ┤ E.2: Telemetry → Prometheus (0.5d)
       ┤ E.3: ADRs 006-008 (0.5d)
       ┤                                    → Score target: ~8.8/10
```

---

## Score Projection

| Dimension | Baseline | After A | After B | After C | After D | After E |
|-----------|----------|---------|---------|---------|---------|---------|
| Domain Purity | 10 | 10 | 10 | 10 | 10 | 10 |
| CQRS Enforcement | 7 | 7 | 9 | 9 | 9 | 9 |
| Dependency Direction | 6 | 6 | 8 | 9 | 9 | 9 |
| Security Boundary Integrity | 5 | 7 | 8 | 8 | 9 | 9 |
| Observability | 2 | 7 | 7 | 7 | 8 | 8 |
| Test Architecture | 8 | 8 | 8 | 8 | 9 | 9 |
| DI / IoC Consistency | 5 | 5 | 9 | 9 | 9 | 9 |
| State Management | 3 | 8 | 8 | 8 | 9 | 9 |
| Async Hygiene | 5 | 5 | 5 | 8 | 8 | 8 |
| Error Handling | 5 | 8 | 8 | 8 | 8 | 8 |
| **Weighted Average** | **6.8** | **7.5** | **8.1** | **8.4** | **8.7** | **8.8** |

---

## Risk Register

| # | Risk | Probability | Mitigation |
|---|------|------------|------------|
| R-A | CLI DI migration breaks undocumented CLI workflows | Medium | Run full CLI test suite before/after; smoke-test all 10 subcommands |
| R-B | Async conversion of PowerShellTool introduces new race conditions | Low | The tool is single-threaded — replacing `subprocess.run` with `create_subprocess_exec` is a 1:1 translation |
| R-C | Settings decoupling requires updating `tool_registry.py` call sites across multiple flows | Medium | Use `ToolConfig` with defaults matching current values; no behavioral change |
| R-D | Adding `save_session()` to `_emit()` changes performance profile of hot loops | Low | `save_session` already called in `ChatFlow._emit()` and in `TaskRunner` — proven pattern; SQLite WAL handles concurrent writes |

---

## Success Criteria

1. **All 8 fitness test gaps filled** (test count goes from 12 → 20+)
2. **`make lint-imports` passes clean** (currently broken by contract overlap)
3. **`curl /api/prometheus` returns non-zero counters** after a single session
4. **`PlanActFlow` sessions survive process restart** — reload and verify all events
5. **Zero `SQLiteStateRepository()` constructions outside `di.py`** in production code
6. **Zero `subprocess.run()` in async functions** per CI gate
7. **Zero `WeebotSettings` imports in `weebot/tools/`** per CI gate
8. **PowerShellTool blocks dangerous commands** regardless of SandboxPort injection — verified by penetration test
9. **Global exception handler catches unhandled exceptions** in both CLI and Web paths
10. **All ADRs (001–008) present and audit-trail linked**
