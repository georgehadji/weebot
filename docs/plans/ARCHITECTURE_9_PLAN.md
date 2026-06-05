# Architecture Score Improvement Plan: 7.8 → 9.0+

**Baseline:** ARCH-AUDIT-V2 (2025-07-18) — 7.8/10, 0 CRITICAL, 2 HIGH, 7 MEDIUM  
**Target:** ≥9.0/10  
**Strategy:** Close every acknowledged debt item, then harden observability and enforcement to zero-tolerance.

---

## Score Drivers — What Moves the Needle

| Dimension | Current | Target | Required Changes |
|-----------|---------|--------|------------------|
| Layer separation | 9/10 | 10/10 | Fix D1 (PowerShellTool langchain) — the only remaining boundary violation |
| Pattern consistency | 8/10 | 10/10 | Fix D2 (3 sqlite3 tools) + D4 (get_event_bus caller) — close all importlinter carve-outs |
| Observability | 6/10 | 9/10 | Add OTEL tracing + structured logging + Prometheus metrics wiring |
| Testability | 7/10 | 9/10 | Enforce async test consistency + add contract tests for all 32 ports |
| Scalability | 7/10 | 9/10 | Split SQLite per-domain + add PostgreSQL adapter + add session-level retry |

## Sequencing — 4 Phases, ~18 Person-Days

**Phase A: Close Debt (days 1–4)** — Fix D1, D2, D4, D5, D8, D9. Removes all acknowledged violations.  
**Phase B: Harden Observability (days 5–8)** — OTEL tracing, structured logging, Prometheus endpoint.  
**Phase C: Harden Testability (days 9–12)** — Contract tests per port, async consistency, CI gate.  
**Phase D: Scale Architecture (days 13–18)** — PostgreSQL adapter, per-domain DB split, session retry.

Each phase ends with a re-score checkpoint. Score should cross 9.0 after Phase C (without Phase D's scalability work, since the rubric permits local-first scope). Phase D pushes to 9.5+.

---

## Phase A: Close All Acknowledged Debt (Days 1–4)

### A1. Rewrite PowerShellTool [D1] — 1 day

**Target:** `weebot/tools/powershell_tool.py`

Replace `langchain.tools.BaseTool` inheritance with `weebot.tools.base.BaseTool`. Route execution through `SandboxPort.execute_shell()`. Keep PowerShell-specific command construction but delegate actual subprocess execution to the sandbox.

- Remove `from langchain.tools import BaseTool` and `class PowerShellTool(BaseTool)`
- Add `SandboxPort` constructor injection
- PowerShell command strings go through sandbox; no direct `subprocess`
- Remove the `DIAGNOSTIC_COMMANDS` classvar dependency on `_WORKSPACE_ROOT` at class-definition time (use property or lazy init)
- Remove `_wsl_available()` probe from bash_tool.py if it's the only `import subprocess` remaining there

**Verification:**
```bash
grep -rn 'from langchain' weebot/tools/ --include='*.py'   # Expected: 0
grep -rn 'import subprocess' weebot/tools/ --include='*.py' # Expected: 0 (or only in sandbox adapters)
pytest tests/unit/ -k powershell -v
```

**Risk:** LOW — isolated rewrite. PowershellTool has ~280 lines; the wrapper pattern is already established by bash_tool.py which uses SandboxPort correctly [bash_tool.py:1-30].

---

### A2. Inject ToolRepositoryPort into 3 sqlite3 Tools [D2] — 1 day

**Targets:** `weebot/tools/knowledge_tool.py`, `product_tool.py`, `video_ingest_tool.py`, `weebot/application/di.py`, `.importlinter`

Add `ToolRepositoryPort` constructor parameter to each tool. Replace direct `sqlite3` calls with port method calls (`tool_repo.query(...)`, `tool_repo.execute(...)`). Remove `import sqlite3`. Update DI container to inject the port. Remove the 3 tools from `.importlinter` `ignore_imports`.

The `ToolRepositoryPort` already exists at `weebot/application/ports/tool_repository_port.py` and `SQLiteToolRepository` adapter is wired in `configure_defaults()` at `di.py:166`. This is wiring-only — no new port needed.

**Verification:**
```bash
grep -rn 'import sqlite3' weebot/tools/ --include='*.py'   # Expected: 0
lint-imports                                                  # Expected: clean
pytest tests/unit/ -k 'knowledge or product or video_ingest' -v
```

**Risk:** LOW — behavior-preserving refactor. All three tools already have simple sqlite3 usage patterns (parameterized queries, no complex transactions).

---

### A3. Eliminate get_event_bus() + Remove Deprecated Shims [D4, D9] — 0.5 days

**Targets:** `weebot/infrastructure/notifications/windows_toast.py`, `weebot/infrastructure/event_bus.py`, `weebot/agent_core_v2.py`, `weebot/state_coordinator.py`, `weebot/state_manager.py`, `weebot/__init__.py`

1. Replace `get_event_bus()` call in `windows_toast.py:235` with `Container.get(EventBusPort)` — the module already imports from the application layer
2. Remove `get_event_bus()` function + module-level `_event_bus` global from `event_bus.py`
3. Verify zero remaining callers of deprecated root shims (`agent_core_v2.py`, `state_coordinator.py`, `state_manager.py`)
4. Delete them if zero callers; otherwise add hard `RuntimeError` on import (not just DeprecationWarning) with sunset date
5. Clean up `weebot/__init__.py` `__getattr__` lazy shims

**Verification:**
```bash
grep -rn 'get_event_bus()' weebot/ --include='*.py'          # Expected: 0
ls weebot/*.py                                                 # Expected: __init__.py only
```

**Risk:** LOW — 1 active call site for get_event_bus. Root shims already emit DeprecationWarning; need to confirm zero importers first.

---

### A4. Type Session.context [D5] — 1 day

**Target:** `weebot/domain/models/session_context.py` (new), `weebot/domain/models/session.py`

Define `SessionContext(BaseModel)` with typed fields:

```python
class SessionContext(BaseModel):
    skill_name: Optional[str] = None
    skill_content: Optional[str] = None
    _original_task: Optional[str] = None
    facts: dict[str, Any] = Field(default_factory=dict, max_length=100)
    # ... any other keys found via search
```

Replace `Session.context: Dict[str, Any]` with `Session.context: SessionContext`. Add eviction policy for `facts` (LRU, pop oldest on insert when len > 100). Update all access sites to use attribute access instead of dict key access.

**Verification:**
```bash
grep -rn "context\[" weebot/application/ --include='*.py'   # Should find only test/legacy references
pytest tests/unit/domain/ -k session -v
```

**Risk:** MEDIUM — changes the public API of `Session.context` from dict to model. Dict-like access (`context["key"]`) breaks. Mitigation: add `__getitem__`/`__setitem__` to SessionContext for backward compatibility during transition, with deprecation warning.

---

### A5. Split CLI main.py [D8] — 0.5 days

**Target:** `cli/main.py` → `cli/commands/`

Extract command groups into:
- `cli/commands/flow.py` — `flow run`, `flow list`, `flow resume`, `flow cancel`
- `cli/commands/agents.py` — `agents list`, `agents route`, `agents sync-claude`
- `cli/commands/skills.py` — skill-related commands
- `cli/commands/harness.py` — harness-related commands

Keep `cli/main.py` as Click group registration only. Target: main.py < 200 lines (from ~1500).

**Verification:**
```bash
wc -l cli/main.py                                             # Expected: < 200
python -m cli.main --help                                      # All commands still listed
python -m cli.main flow list                                   # Functional
python -m cli.main health                                      # Functional
```

**Risk:** LOW — file moves, no logic changes. Click groups are designed for this split pattern.

---

### Phase A Checkpoint

| Dimension | Before | After A |
|-----------|--------|---------|
| Layer separation | 9/10 | **10/10** (D1 fixed) |
| Pattern consistency | 8/10 | **10/10** (D2, D4 fixed) |
| Overall score | 7.8 | **~8.5** |

---

## Phase B: Harden Observability (Days 5–8)

### B1. Wire OTEL Distributed Tracing — 2 days

**Targets:** `weebot/infrastructure/observability/tracing.py` (new), `mediator.py`, `plan_act_flow.py`, `resilient_adapter.py`

Add `opentelemetry-api` + `opentelemetry-sdk` + `opentelemetry-exporter-otlp` dependencies.

Create `TracingConfig` and `init_tracing()` in infrastructure:

```python
# weebot/infrastructure/observability/tracing.py
def init_tracing(service_name: str, otlp_endpoint: Optional[str] = None):
    provider = TracerProvider(...)
    if otlp_endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    trace.set_tracer_provider(provider)
```

Instrument:
- `Mediator.send()` — span per command (name = command class name, attributes = session_id)
- `LLMPort.chat()` — span per LLM call (attributes = provider, model, input_tokens, output_tokens)
- `PlanActFlow` state transitions — span per state (attributes = flow_name, session_id)
- `Tool.execute()` — span per tool call (attributes = tool_name, risk_level)

Use existing `session.id` and `plan.id` as trace context carriers. Inject traceparent into Session.context for cross-flow propagation.

**Verification:**
```bash
pytest tests/integration/ -k tracing -v
# Manual: run a flow with OTEL_EXPORTER_OTLP_ENDPOINT set, verify spans in collector
```

**Risk:** MEDIUM — new dependency, new infrastructure concern. Mitigation: OTLP endpoint is optional; when unset, tracing is no-op (uses `NoOpTracerProvider`).

---

### B2. Complete Structured Logging Migration — 1 day

**Targets:** `weebot/application/flows/`, `weebot/application/agents/`, `weebot/infrastructure/adapters/`

Replace remaining `logging.getLogger(__name__)` calls with `structlog.get_logger()` across all flows, agents, and adapters. Bind `session_id`, `flow_name`, `agent_name` as structlog context variables. Configure dual renderer: JSON for production (`WEEBOT_LOG_FORMAT=json`), console for dev.

Ensure all WARNING+ log events include `trace_id` and `span_id` from OTEL context (if available).

**Verification:**
```bash
grep -rn 'logging.getLogger' weebot/application/ weebot/infrastructure/ --include='*.py' \
  | grep -v '__init__' | grep -v 'test_'                         # Expected: 0
python -m cli.main flow run "test" 2>&1 | head -1 | python -m json.tool  # Valid JSON with session_id
```

**Risk:** LOW — additive change. structlog is already a dependency; this completes the migration. Console fallback ensures no log loss.

---

### B3. Wire Prometheus Metrics Endpoint — 1 day

**Targets:** `weebot/interfaces/web/main.py`, `weebot/infrastructure/observability/metrics.py` (new), `weebot/application/ports/metrics_port.py` (new)

Add `GET /metrics` endpoint to FastAPI app returning `prometheus_client.generate_latest()`. Register counters and histograms:

| Metric | Type | Labels |
|--------|------|--------|
| `weebot_llm_calls_total` | Counter | provider, model, tier, status |
| `weebot_command_duration_seconds` | Histogram | command_type |
| `weebot_tool_executions_total` | Counter | tool_name, risk_level, status |
| `weebot_sessions` | Gauge | status |
| `weebot_event_bus_messages_total` | Counter | event_type |

Define `MetricsPort` in `application/ports/` for test doubles. Wire real implementation via `configure_defaults()`. Instrument the same call sites as tracing (B1).

**Verification:**
```bash
curl -s http://localhost:8000/metrics | grep 'weebot_'           # Multiple metric lines
curl -s http://localhost:8000/metrics | grep 'weebot_llm_calls_total'  # Present
pytest tests/unit/ -k metrics -v
```

**Risk:** LOW — `prometheus-client` is already a dependency (was listed but unused per V2 audit). This just completes wiring. `/metrics` endpoint requires auth middleware (trivial API key check).

---

### Phase B Checkpoint

| Dimension | After A | After B |
|-----------|---------|---------|
| Observability | 6/10 | **9/10** (tracing + logging + metrics) |
| Overall score | ~8.5 | **~8.8** |

---

## Phase C: Harden Testability & Enforcement (Days 9–12)

### C1. Contract Tests for All 32 Ports — 2 days

**Target:** `tests/unit/test_port_contracts.py` (new)

For each port in `application/ports/`, create a contract test class that:

1. Verifies the port ABC is importable
2. Verifies the registered adapter class implements all abstract methods (via `issubclass` + `inspect`)
3. Verifies the adapter can be constructed via DI (`container.get(PortType)`)
4. Verifies method signatures match (parameter names, return type annotations)

Use `pytest.mark.parametrize` over a list of `(PortType, AdapterType, container_factory)` tuples. Catch any port with zero registered adapters or dead adapter references. Flag with `@pytest.mark.skip` + TODO comment.

**Verification:**
```bash
pytest tests/unit/test_port_contracts.py -v                     # All 32 ports pass or have documented skip
```

**Risk:** LOW — read-only verification. No behavior change. Catches regressions when ports are added without adapters.

---

### C2. Enforce Async Test Consistency — 1 day

**Targets:** `pytest.ini`, `tests/`, `.github/workflows/test.yml`

Add `asyncio_mode = auto` to `pytest.ini` (or `[tool.pytest.ini_options]` in `pyproject.toml`). This makes all `async def` tests automatically use asyncio without `@pytest.mark.asyncio` decorator.

Audit all test files:
- Any test calling async code must be `async def`
- All mock coroutines must use `AsyncMock` (not `Mock` with `return_value` for coroutines)
- Remove all `@pytest.mark.asyncio` decorators (no longer needed in auto mode)

Add CI lint rule: forbid `@pytest.mark.asyncio` in test files (should be auto-detected). Add pre-commit hook or CI step that runs `grep -rn '@pytest.mark.asyncio' tests/` and fails if found.

**Verification:**
```bash
grep -rn '@pytest.mark.asyncio' tests/                           # Expected: 0
pytest tests/ -v --tb=short                                       # All pass
```

**Risk:** LOW — mechanical change. `asyncio_mode = auto` is the recommended pytest-asyncio configuration. Some tests may need `Mock` → `AsyncMock` fixes.

---

### C3. Architecture Fitness: Zero Carve-Outs — 1 day

**Target:** `tests/unit/test_architecture_fitness.py`

After Phase A completes (all debt closed), update `test_architecture_fitness.py` to remove ALL exception/carve-out lists:

| Carve-out | Removed by |
|-----------|-----------|
| `allowed_exceptions = {"di.py", "__init__.py"}` | Already legitimate (DI container needs infra imports) — keep but narrow to specific import lines |
| `known_exception_tools = {"knowledge_tool", "product_tool", "video_ingest_tool"}` | A2 |
| `known_exceptions` (sync-call files) | A1 + A3 |
| `allowed_files` + `allowed_dirs` (root flat files) | A3 |

Target: all architecture fitness tests pass with **zero** carve-out lists. If any legitimate exception remains (e.g., `di.py` importing infrastructure), document with an inline comment referencing a specific ADR.

**Verification:**
```bash
pytest tests/unit/test_architecture_fitness.py -v                # All pass, zero skips
```

**Risk:** MEDIUM — fitness tests may uncover additional violations that weren't in the debt register. Mitigation: run first, triage any new findings, fix or document before proceeding.

---

### Phase C Checkpoint

| Dimension | After B | After C |
|-----------|---------|---------|
| Testability | 7/10 | **9/10** (contract tests + async consistency + zero carve-outs) |
| Overall score | ~8.8 | **~9.1** ✅ |

**Score crosses 9.0 here.** Phase D is for scalability — pushes to 9.5+ but is not required for the 9.0 target.

---

## Phase D: Scale Architecture (Days 13–18)

### D1. Add PostgreSQL Adapter + Per-Domain DB Split — 3 days

**Targets:** `weebot/infrastructure/persistence/postgresql/` (new), `weebot/config/settings.py`, `alembic/`

Create PostgreSQL adapter package implementing the same ports as SQLite:

| Port | SQLite Adapter | PostgreSQL Adapter (new) |
|------|---------------|--------------------------|
| `StateRepositoryPort` | `SQLiteStateRepository` | `PostgreSQLStateRepository` |
| `KnowledgeGraphPort` | `SQLiteKnowledgeGraph` | `PostgreSQLKnowledgeGraph` |
| `SummaryRepoPort` | `SQLiteSummaryRepo` | `PostgreSQLSummaryRepo` |
| `ToolRepositoryPort` | `SQLiteToolRepository` | `PostgreSQLToolRepository` |

Use `asyncpg` for async connection pooling. Add `WEEBOT_DB_BACKEND` setting (`sqlite` / `postgresql`). DI container selects adapter based on setting. Add Alembic for migration management. Keep SQLite as default for local-first usage.

**Per-domain DB split:** When `WEEBOT_DB_BACKEND=postgresql`, use separate databases per domain (`weebot_sessions`, `weebot_skills`, `weebot_cache`) with independent connection pools.

**Verification:**
```bash
WEEBOT_DB_BACKEND=postgresql pytest tests/integration/ -k persistence -v  # All pass
alembic upgrade head                                                       # Runs clean
alembic downgrade base                                                     # Reversible
```

**Risk:** HIGH — new infrastructure, data migration, deployment coordination. Mitigation:
- SQLite remains default; PostgreSQL behind feature flag
- Alembic migrations tested in CI
- Dual-write period for gradual migration (optional, can skip for initial deploy)
- Per-domain DB split is additive (connects to same PG server, different databases)

---

### D2. Add Session-Level Retry [D6] — 1 day

**Targets:** `weebot/application/services/task_runner.py`, `weebot/application/ports/task_queue_port.py`

Add `max_session_retries` (default 3) to `TaskRunner` with exponential backoff between retries. On all-LLM-tiers-down failure:

1. Increment `session.retry_count`
2. If `retry_count <= max_session_retries`, requeue with delay = `base_delay * (2 ** retry_count)` + jitter
3. If exhausted, save session as `FAILED_PERMANENT`

Add `TaskRunnerPort.requeue(session_id, delay_seconds)` method. Wire retry logic in `TaskRunner._handle_failure()`. Log each retry with structured logger at WARNING level.

**Verification:**
```bash
pytest tests/integration/ -k 'retry or task_runner' -v
# Test: mock all 3 LLM tiers to fail, verify session is retried 3 times, then FAILED_PERMANENT
# Test: mock LLM recovery on 2nd retry, verify session completes
```

**Risk:** MEDIUM — changes failure semantics. Mitigation: feature flag (`WEEBOT_SESSION_RETRY_ENABLED`), default off initially. Idempotent tool execution is already handled (tools have no automatic retry — D6 is about the orchestration layer, not tool re-execution).

---

### Phase D Checkpoint

| Dimension | After C | After D |
|-----------|---------|---------|
| Scalability | 7/10 | **9/10** (PostgreSQL + per-domain DB + session retry) |
| Overall score | ~9.1 | **~9.4** |

---

## Full Sprint Schedule

```
Day 1   ┤ A1: PowerShellTool rewrite (1d)
Day 2   ┤ A2: ToolRepositoryPort injection (1d)
Day 3   ┤ A3: get_event_bus + root shims (0.5d)
        ┤ A4: SessionContext typing (0.5d of 1d)
Day 4   ┤ A4: SessionContext typing (remaining 0.5d)
        ┤ A5: CLI split (0.5d)
        ┤ Phase A checkpoint re-score
Day 5   ┤ B1: OTEL tracing (1d of 2d)
Day 6   ┤ B1: OTEL tracing (remaining 1d)
Day 7   ┤ B2: Structured logging (1d)
Day 8   ┤ B3: Prometheus metrics (1d)
        ┤ Phase B checkpoint re-score
Day 9   ┤ C1: Contract tests (1d of 2d)
Day 10  ┤ C1: Contract tests (remaining 1d)
Day 11  ┤ C2: Async test consistency (1d)
Day 12  ┤ C3: Zero carve-outs (1d)
        ┤ Phase C checkpoint re-score → should cross 9.0 ✅
Day 13  ┤ D1: PostgreSQL adapter (1d of 3d)
Day 14  ┤ D1: PostgreSQL adapter (1d of 3d)
Day 15  ┤ D1: PostgreSQL adapter (remaining 1d)
Day 16  ┤ D2: Session retry (1d)
        ┤ Buffer / integration testing
Day 17  ┤ Buffer / cross-cutting regression tests
Day 18  ┤ Final ARCH-AUDIT-V3 re-score
        ┤ Update ARCHITECTURE.md
```

---

## Risk Register

| # | Risk | Phase | Severity | Mitigation |
|---|------|-------|----------|------------|
| R1 | SessionContext breaks dict-access callers | A4 | MED | Add `__getitem__`/`__setitem__` shim with deprecation warning |
| R2 | Fitness test zero-carveout uncovers new violations | C3 | MED | Run first, triage, fix or document before marking complete |
| R3 | PostgreSQL migration breaks existing SQLite tests | D1 | HIGH | Feature flag; CI runs both backends; SQLite remains default |
| R4 | Session retry causes duplicate tool execution | D2 | HIGH | Retry only at orchestration layer; tools have no auto-retry; idempotency already handled |
| R5 | OTEL exporter impacts latency | B1 | LOW | Optional; no-op when endpoint unset; BatchSpanProcessor avoids per-span I/O |

---

## Success Metrics

| Metric | Baseline | Target |
|--------|----------|--------|
| Architecture score | 7.8/10 | ≥ 9.0/10 |
| CRITICAL violations | 0 | 0 |
| HIGH violations | 2 (D1) | 0 |
| MEDIUM debt items | 7 | 0 |
| import-linter carve-outs | 4 | 0-1 (DI container only) |
| Ports with contract tests | 0/32 | 32/32 |
| Structured logging coverage | Partial | 100% in application + infrastructure |
| Prometheus metrics endpoint | Absent | Present + instrumented |
| Async test consistency | Partial | Enforced in CI |
| PostgreSQL support | None | Feature-flagged, migration-tested |
| Session retry | None | 3 retries with backoff |
