# Architecture Enhancement Plan — Target > 9.2 / 10

**Baseline Score:** 8.7 / 10 (June 2026 Post-Remediation Audit)  
**Target Score:** ≥ 9.2 / 10  
**Overall Delta:** +0.5 points minimum  
**Estimated Effort:** 10–12 person-days across 3 sprints  
**Last Updated:** 2026-06-01

---

## Score Trajectory

| Dimension | Current | Target | Delta | Key Driver |
|-----------|---------|--------|-------|------------|
| Domain Purity | 10 / 10 | 10 / 10 | — | Preserve |
| CQRS Enforcement | 9 / 10 | 10 / 10 | +1 | SavePolicyBehavior + orphan command resolution |
| Dependency Direction | 9 / 10 | 10 / 10 | +1 | core/ physical move + root shim cleanup |
| Security Boundary Integrity | 8 / 10 | 9 / 10 | +1 | Browser pool, circuit breaker integration tests |
| Observability | 8 / 10 | 9 / 10 | +1 | Telemetry→Prometheus, performance benchmarks |
| Test Architecture | 9 / 10 | 10 / 10 | +1 | Performance tests, coverage gap closure, CI completeness |
| DI / IoC Consistency | 9 / 10 | 10 / 10 | +1 | _default_container elimination |
| State Management | 9 / 10 | 9 / 10 | — | SavePolicyBehavior is structural, not scoring |
| Async Hygiene | 8 / 10 | 9 / 10 | +1 | Remaining sync helpers audited + documented |
| Error Handling | 8 / 10 | 9 / 10 | +1 | CLI error handling completeness |
| **Weighted Average** | **8.7** | **9.4** | **+0.7** | |

---

## Phase 1 — Closure (Week 1, ~3 days)

> Resolve the 3 remaining High/Medium findings from the June 2026 audit.

### 1.1 EventStorePort Orphan Resolution (1 day)

**Problem:** `EventStorePort` ABC (`application/ports/event_store_port.py:14`) has no implementing adapter. `EventStore` in `infrastructure/event_store.py:91` is a standalone class that doesn't inherit from it. Any code depending on `EventStorePort` via DI will fail to resolve.

**Decision:** Implement the port contract. `EventStore` should inherit from `EventStorePort`.

| Step | File | Action |
|------|------|--------|
| 1.1.1 | `infrastructure/event_store.py:91` | Change `class EventStore` → `class EventStore(EventStorePort)`. Add `@abstractmethod` implementations for any missing methods. |
| 1.1.2 | `application/ports/event_store_port.py` | Audit abstract methods — confirm all are implemented in `EventStore`. If any are unused, add a note. |
| 1.1.3 | `application/di.py` | Register `EventStorePort` binding: `self.register(EventStorePort, lambda: self._create_event_store())` |
| 1.1.4 | `tests/unit/test_event_store_port.py` | New test: verify `isinstance(EventStore(), EventStorePort)` is True |
| 1.1.5 | `tests/unit/test_architecture_fitness.py` | Update `port_adapter_map` to include `EventStorePort` → `EventStore` |

**Verification:**
```python
from infrastructure.event_store import EventStore
from application.ports.event_store_port import EventStorePort
assert issubclass(EventStore, EventStorePort)
```

### 1.2 Orphan Command Resolution (0.5 day)

**Problem:** `AskUserCommand` (`commands.py:73`) and `AnswerUserCommand` (`commands.py:85`) are defined but never registered in `register_default_handlers()`.

**Decision:** Delete them. The `WaitForUserEvent` domain event already handles human-in-the-loop. These commands duplicate that functionality without handlers.

| Step | File | Action |
|------|------|--------|
| 1.2.1 | `commands.py` | Delete `AskUserCommand` and `AnswerUserCommand` class definitions |
| 1.2.2 | `commands.py` | Remove their `model_rebuild()` calls |
| 1.2.3 | `tests/unit/test_architecture_fitness.py` | Confirm `test_every_command_has_handler` still passes (14 → 12 commands) |

**Verification:**
```bash
grep -rn "AskUserCommand\|AnswerUserCommand" weebot/ --include="*.py" | grep -v test_ | grep -v docs/
# Expected: 0 results
```

### 1.3 Root Shim Audit (0.5 day)

**Problem:** 32 root-level shims from Phase 3 produce `DeprecationWarning` on every import. Sunset date (2026-09-01) is approaching.

**Action:** Audit which shims have zero remaining importers and can be deleted now. Tag remaining shims with automated CI check.

| Step | File | Action |
|------|------|--------|
| 1.3.1 | All 32 shims | For each shim, `grep -rn "from weebot.<shim>" weebot/ --include="*.py" \| grep -v __pycache__`. If result count = 0: delete the shim now. |
| 1.3.2 | Remaining shims | Update LEGACY header with expected removal date and migration instruction |
| 1.3.3 | `tests/unit/test_architecture_fitness.py` | Add `test_no_unexpected_shim_imports` — fails if any new code imports a shim (catches drift) |

### 1.4 SavePolicyBehavior (1 day)

**Problem:** `PlanActFlow._emit()` and `ChatFlow._emit()` both call `save_session()` independently. A new flow must remember to implement persistence.

**Fix:** Create a pipeline behavior that auto-saves session state after every successful command handler.

| Step | File | Action |
|------|------|--------|
| 1.4.1 | `application/cqrs/behaviors/save_policy.py` | Create `SavePolicyBehavior(IPipelineBehavior)`. In `handle()`, after the handler completes, if `request` has a `session_id` field, load and save via `state_repo`. |
| 1.4.2 | `application/di.py` | Register `SavePolicyBehavior` in `build_mediator()` after `LoggingBehavior` |
| 1.4.3 | `application/flows/plan_act_flow.py` | Remove inline `self._state_repo.save_session(self._session)` from `_emit()` — persistence is now a pipeline concern |
| 1.4.4 | `application/flows/chat_flow.py` | Same — remove inline save |
| 1.4.5 | `tests/unit/test_save_policy.py` | New test: verify handler completes → session is persisted |
| 1.4.6 | `tests/unit/test_architecture_fitness.py` | Add `test_save_policy_registered` — verify mediator has `SavePolicyBehavior` in pipeline |

---

## Phase 2 — Structural Cleanup (Week 2, ~4 days)

> Eliminate god modules, root shims, and singleton patterns that hold the architecture below 9.0.

### 2.1 CLI God Module Decomposition (2 days)

**Problem:** `cli/main.py` is 1,006 lines with 39 leaf commands in one file. The `cli()` function is 683 lines.

**Fix:** Split into `cli/commands/` subdirectory, one file per command group.

| Step | File | Action |
|------|------|--------|
| 2.1.1 | `cli/commands/__init__.py` | Create package init |
| 2.1.2 | `cli/commands/flow_commands.py` | Extract 6 flow commands (flow_run, flow_resume, flow_list, flow_cancel, flow_undo, flow_export) → ~200 lines |
| 2.1.3 | `cli/commands/benchmark_commands.py` | Extract 4 benchmark commands → ~150 lines |
| 2.1.4 | `cli/commands/agent_commands.py` | Extract 7 agent commands + 2 pack subcommands → ~250 lines |
| 2.1.5 | `cli/commands/research_commands.py` | Extract 3 research commands → ~120 lines |
| 2.1.6 | `cli/commands/hooks_commands.py` | Extract 2 hooks commands → ~50 lines |
| 2.1.7 | `cli/commands/flat_commands.py` | Extract 15 top-level commands (create, list, status, run, resume, etc.) → ~300 lines |
| 2.1.8 | `cli/main.py` | Reduce to imports + `cli()` group definition + `if __name__ == "__main__"` wrapper → ~80 lines |
| 2.1.9 | All extracted files | Replace direct `SQLiteStateRepository()` usage with `_get_state_repo()` (already refactored in Phase B.1 — verify no regression) |

**Verification:**
```bash
wc -l cli/main.py cli/commands/*.py
# cli/main.py: ~80
# Each command file: <300
# Total: ~1,000 (same functionality, modular)
```

### 2.2 Root Shim Deletion (1 day)

**Problem:** 32 root shims create ~600 lines of dead code and confuse new developers.

**Fix:** Delete shims with zero importers. For shims with remaining importers, bump the sunset date and add a CI check.

| Step | Action |
|------|--------|
| 2.2.1 | `grep -rn "from weebot.<file>" weebot/ --include="*.py" \| grep -v __pycache__` for each shim. Delete all with zero results. |
| 2.2.2 | For remaining shims: update LEGACY header with "Last audit: 2026-07-01. Remaining importers: N." |
| 2.2.3 | `tests/unit/test_architecture_fitness.py` — add `test_no_new_shim_imports` (fails if file count in `weebot/` root exceeds the allowlist count from Phase 3) |

### 2.3 `_default_container` Elimination (0.5 day)

**Problem:** `application/di.py:643` exposes a module-level `_default_container` singleton. This prevents multi-process setup and makes testing harder.

| Step | File | Action |
|------|------|--------|
| 2.3.1 | `application/di.py` | Remove `_default_container` and `get_container()`. Replace all callers with explicit `Container()` + `configure_defaults()`. |
| 2.3.2 | `cli/main.py` | Replace `get_container().get()` → create `Container()` once in `cli()` function, pass to command groups |
| 2.3.3 | `run.py` | Replace `get_container()` → create `Container()` in `run_interactive()` |
| 2.3.4 | `interfaces/web/main.py` | Already creates explicit `Container()` — no change needed |
| 2.3.5 | `tests/unit/test_di_singleton.py` | New test: verify no module-level `_default_container` exists |

### 2.4 Route All Remaining `WeebotSettings` Imports Through `ToolConfig` (0.5 day)

**Problem:** After Phase C.2, `bash_tool.py` and `python_tool.py` added `set_config()` but retain legacy `_get_settings()` imports. `file_editor.py` and `powershell_tool.py` never received `set_config()`.

| Step | File | Action |
|------|------|--------|
| 2.4.1 | `tools/file_editor.py` | Add `set_config(self, config: ToolConfig)` method + `_tool_config` PrivateAttr. Replace `_get_settings()` calls with `self._tool_config`. |
| 2.4.2 | `tools/powershell_tool.py` | Add `_tool_config` PrivateAttr. Update `_get_max_timeout()` to read from it. |
| 2.4.3 | `tools/bash_tool.py` | Remove `_get_settings()` helper — all config now through `set_config()` |
| 2.4.4 | `tools/python_tool.py` | Same |
| 2.4.5 | `tools/tool_registry.py` | Extend `_sandbox_port_tools` set to include `"file_editor"`; inject `tool_config` for it |
| 2.4.6 | `tests/unit/test_architecture_fitness.py` | Remove `file_editor.py` and `powershell_tool.py` from `settings_exceptions` — they now comply |

---

## Phase 3 — Hardening & Observability (Week 3, ~4 days)

> Close the remaining gaps in testing, observability, and architectural enforcement.

### 3.1 Telemetry → Prometheus Wire-Up (0.5 day)

**Problem:** `behaviors/telemetry.py` logs CQRS execution duration to Python's `logging` but never touches Prometheus.

| Step | File | Action |
|------|------|--------|
| 3.1.1 | `behaviors/telemetry.py` | Replace `logging.info("Handler X took Y seconds")` with `flow_step_duration_seconds.labels(flow_type, state).observe(duration)` |
| 3.1.2 | `infrastructure/observability/metrics.py` | Add `Used by: behaviors/telemetry.py, task_runner.py, event_bus.py` to docstring |

### 3.2 Performance Test Infrastructure (1 day)

**Problem:** No performance / load tests exist. No way to detect latency regression in LLM calls or tool execution.

| Step | File | Action |
|------|------|--------|
| 3.2.1 | `requirements.txt` | Add `pytest-benchmark>=4.0` |
| 3.2.2 | `tests/perf/test_llm_benchmark.py` | Benchmark: `ResilientAdapter.chat()` with mock HTTP, measure p50/p95/p99 latency |
| 3.2.3 | `tests/perf/test_tool_benchmark.py` | Benchmark: `ToolCollection.execute()` with mock subprocess, measure execution latency |
| 3.2.4 | `tests/perf/test_flow_throughput.py` | Throughput: run 10 sessions through `TaskRunner`, measure events/second |
| 3.2.5 | `Makefile` | Add `bench` target: `pytest tests/perf/ --benchmark-only` |

### 3.3 Browser Pool + Circuit Breaker Integration Tests (1 day)

**Problem:** `infrastructure/browser/session_pool.py` pool exhaustion behavior is untested. `core/circuit_breaker.py` opening under consecutive failures is untested.

| Step | File | Action |
|------|------|--------|
| 3.3.1 | `tests/integration/test_browser_pool.py` | Create pool, exhaust it with concurrent requests, verify error handling |
| 3.3.2 | `tests/unit/test_circuit_breaker.py` | Add test: 5 consecutive failures → circuit opens → half-open after cooldown → success closes it |
| 3.3.3 | `tests/unit/test_architecture_fitness.py` | Add `test_browser_pool_has_limits` — verify pool config has max_size set |
| 3.3.4 | `infrastructure/browser/session_pool.py` | Add explicit `max_size` parameter (if missing) with default of 5 |

### 3.4 CI Fitness Test Completeness (1 day)

**Problem:** Architecture fitness tests cover 18 rules, but some gaps remain:
- No test prevents `EventStorePort` repetition (new orphan port would not be caught)
- No test verifies all `IPipelineBehavior` subclasses are registered

| Step | File | Action |
|------|------|--------|
| 3.4.1 | `tests/unit/test_architecture_fitness.py` | Add `test_all_ports_have_binding_in_di` — parse `di.py`, verify every `<Port>Port` class in `ports/` has a `self.register(` line |
| 3.4.2 | `tests/unit/test_architecture_fitness.py` | Add `test_all_behaviors_registered` — AST-scan `behaviors/` for `IPipelineBehavior` subclasses, verify each is instantiated in `build_mediator()` |
| 3.4.3 | `tests/unit/test_architecture_fitness.py` | Add `test_no_module_level_settings_in_tools` — stricter version of existing test that fails on any `from weebot.config.settings import` in `tools/` (no exceptions left after Phase 2.4) |
| 3.4.4 | `tests/unit/test_architecture_fitness.py` | Add `test_every_event_type_has_publisher` — for every `AgentEvent` subtype, verify at least one file outside `domain/models/` emits it |

### 3.5 CLI Error Handling Completeness (0.5 day)

**Problem:** After Phase B.1, CLI uses DI container. But `_get_state_repo()` helper has no fallback if `Container.get()` raises `KeyError`.

| Step | File | Action |
|------|------|--------|
| 3.5.1 | `cli/main.py` | Wrap `_get_state_repo()` in try/except `KeyError` → log "DI container not configured" and exit cleanly |
| 3.5.2 | `cli/main.py` | Replace bare `sys.exit(1)` in except block with structured error message + exit code |
| 3.5.3 | `tests/unit/test_cli_error_handling.py` | New test: call CLI with unconfigured container → expect clean exit with message |

---

## Full Sprint Schedule

```
Week 1  ┤ 1.1: EventStorePort fix (1d)
        ┤ 1.2: Orphan command cleanup (0.5d)
        ┤ 1.3: Root shim audit (0.5d)
        ┤ 1.4: SavePolicyBehavior (1d)
        ┤                                    → Score target: ~9.0/10

Week 2  ┤ 2.1: CLI decomposition (2d)
        ┤ 2.2: Root shim deletion (1d)
        ┤ 2.3: _default_container removal (0.5d)
        ┤ 2.4: ToolConfig completion (0.5d)
        ┤                                    → Score target: ~9.3/10

Week 3  ┤ 3.1: Telemetry→Prometheus (0.5d)
        ┤ 3.2: Performance benchmark infra (1d)
        ┤ 3.3: Browser pool + circuit breaker tests (1d)
        ┤ 3.4: CI fitness test completeness (1d)
        ┤ 3.5: CLI error handling (0.5d)
        ┤                                    → Score target: ~9.5/10
```

---

## Architecture Score Projection

| Dimension | Baseline | After Phase 1 | After Phase 2 | After Phase 3 |
|-----------|----------|--------------|--------------|--------------|
| Domain Purity | 10 | 10 | 10 | 10 |
| CQRS Enforcement | 9 | 10 | 10 | 10 |
| Dependency Direction | 9 | 9 | 10 | 10 |
| Security Boundary Integrity | 8 | 8 | 8 | 9 |
| Observability | 8 | 8 | 8 | 9 |
| Test Architecture | 9 | 9 | 9 | 10 |
| DI / IoC Consistency | 9 | 9 | 10 | 10 |
| State Management | 9 | 10 | 10 | 10 |
| Async Hygiene | 8 | 8 | 8 | 9 |
| Error Handling | 8 | 8 | 8 | 9 |
| **Weighted Average** | **8.7** | **9.0** | **9.3** | **9.5** |

---

## Risk Register

| # | Risk | Probability | Mitigation |
|---|------|------------|------------|
| R-A | `SavePolicyBehavior` causes double-save when combined with `_emit()`'s inline save | Medium | Step 1.4.3/1.4.4 removes inline saves — only one persistence point |
| R-B | CLI decomposition breaks Click decorator chain | Medium | Click's `@cli.group()` + `@group.command()` chain is transitive; extracted commands use same decorator pattern |
| R-C | `_default_container` removal breaks `get_container()` callers not yet migrated | Low | Only 2 remaining callers: `cli/main.py` and `run.py` |
| R-D | Root shim deletion unearths hidden importers | Medium | Audit step 1.3.1 catches all importers before deletion |
| R-E | EventStore inheriting from ABC requires implementing all abstract methods | Low | EventStore already has all the methods; just missing the `class EventStore(EventStorePort)` declaration |

---

## Success Criteria

1. `EventStore` inherits from `EventStorePort` — verified by `isinstance()`
2. `grep -rn "AskUserCommand\|AnswerUserCommand" weebot/` returns zero results in non-docs
3. `cli/main.py` is ≤100 lines; all commands in `cli/commands/` subdirectory
4. `grep -rn "from weebot._default_container\|get_container()" weebot/` returns zero results
5. `make bench` runs and produces p50/p95/p99 latency charts
6. Architecture fitness test count goes from 18 → 23+ (Phase 3.4 additions)
7. All phase 2.4 tools (`file_editor`, `powershell`) accept `ToolConfig` via `set_config()`
8. `SavePolicyBehavior` is registered in mediator pipeline
9. `telemetry.py` increments Prometheus `flow_step_duration_seconds` instead of logging.info
10. Browser pool exhaustion test passes with clear error handling
