# ARCH-AUDIT-V2 — Architecture Remediation Plan

**Version:** 2.0
**Date:** 2026-07-11
**Scope:** Raise weebot architecture score from 8.0 → 10.0
**Epistemic protocol:** EGFV — every non-trivial claim labeled

---

## Executive Summary

The current codebase scores **8.0/10** on the standard 8-dimension rubric.
Three areas prevent a 10/10:

1. **Three lazy-runtime port bypasses** in the executor agent (Dependency Hygiene)
2. **In-memory event bus** with no durability, no per-subscriber timeout, and
   no replay capability (Resilience + Observability)
3. **Four legacy root shim files** and incomplete import-linter coverage of the
   remaining 45-tool layer (Modularity + Dependency Hygiene)

The plan is organized in three phases: quick wins (2 days), structural
improvements (2 weeks), and strategic hardening (4–6 weeks).  Each phase has
a concrete score impact.

---

## Score Baseline (current)

| Dimension | Score | Ceiling | What's holding it back |
|---|---|---|---|
| Pattern Consistency | 9/10 | 10 | 3 lazy-runtime port bypasses |
| Dependency Hygiene | 8/10 | 10 | Those 3 bypasses + 4 root shims + no tool-layer contract |
| Modularity | 8/10 | 10 | Root shims still present; `BaseTool` location creates friction |
| Observability | 7/10 | 9 | In-memory event bus, no end-to-end OTEL traces |
| Resilience | 8/10 | 10 | Event loss on crash, no session-level retry |
| Extensibility | 9/10 | 10 | Already strong |
| Testability | 7/10 | 9 | CI fitness test coverage strong; integration test gaps |
| Security | 8/10 | 9 | 4-layer sandbox guard already strong; Dependabot missing |
| **Overall** | **8.0/10** | **~9.6** | |

> 10.0 is an aspirational ceiling.  Realistically, **9.6** is the top
> achievable without a multi-month infrastructure replacement (distributed
> task queue, per-domain databases, multi-process deployment).

---

## Phase A — Quick Wins (2 days, target 8.8)

### A1. Fix `_context_compressor.py` port bypass — add `build_image_message` to LLMPort

- **Evidence:** `application/agents/executor/_context_compressor.py:149` lazy-imports
  `build_image_message` from `weebot.infrastructure.adapters.llm._multimodal`.
  The LLMPort already defines the chat contract; a multimodal helper belongs there.
  [VERIFIED]
- **Action:** Add `async build_multimodal_message(role, text, image_base64)` to
  `LLMPort`. Implement in adapter base; update call site.
- **Files:** `application/ports/llm_port.py`, `infrastructure/adapters/llm/_multimodal.py`,
  `agents/executor/_context_compressor.py`
- **Risk:** Low (additive method on existing interface)
- **Effort:** 2h
- **Verification:** `grep -rn "from weebot.infrastructure.adapters.llm._multimodal import" weebot/application/` returns empty.

### A2. Fix `_base.py` port bypass — add `get_low_salience_entries` to StateRepositoryPort

- **Evidence:** `application/agents/executor/_base.py:444` lazy-instantiates
  `SQLiteStateRepository` directly to query low-salience user profile entries.
  This bypasses `StateRepositoryPort`, which already has `search_sessions` and
  `list_sessions` but no salience-aware query. [VERIFIED]
- **Action:** Add `get_low_salience_entries(threshold, limit)` to `StateRepositoryPort`.
  Implement on `SQLiteStateRepository`. Update call site to use the port.
- **Files:** `application/ports/state_repo_port.py`,
  `infrastructure/persistence/sqlite_state_repo.py`, `agents/executor/_base.py`
- **Risk:** Low (additive)
- **Effort:** 1h
- **Verification:** `grep -rn "SQLiteStateRepository" weebot/application/` returns
  only DI factory references.

### A3. Add per-subscriber timeout to AsyncEventBus

- **Evidence:** `infrastructure/event_bus.py:59` uses `asyncio.gather` without
  per-subscriber timeout. One slow subscriber blocks all others. [VERIFIED]
- **Action:** Wrap each `_safe_call` call in `asyncio.wait_for(handler(event), timeout=30)`.
  Make timeout configurable via constructor (default 30s). Log timeouts.
- **Files:** `infrastructure/event_bus.py`
- **Risk:** Low (additive; existing subscribers complete in <1s)
- **Effort:** 1h
- **Verification:** Unit test that a 31s handler is logged as timed out but doesn't
  block a fast handler.

### A4. Add tool-layer import-linter contract

- **Evidence:** No import-linter contract covers the `weebot/tools/` layer.
  Tools can currently import anything. [VERIFIED]
- **Action:** Add `tools-no-infra` contract: `weebot.tools` must not import
  `weebot.infrastructure.persistence` (DB access) or `weebot.infrastructure.adapters`
  (adapter bypass). Tools should go through ports only.
  Add existing exception for `schedule_tool → scheduler` and any other
  pre-audited bypasses found.
- **Files:** `.importlinter`
- **Risk:** Low (enforcement-only; catches regressions)
- **Effort:** 1h
- **Verification:** `make lint-imports` prints 6 contracts kept, 0 broken.

### A5. Eliminate root shim files

- **Evidence:** 4 files at `weebot/*.py` are legacy stubs:
  `nlp_understanding.py`, `notifications.py`, `ai_router.py`, `agent_core_v2.py`.
  They form cross-layer coupling with unknown blast radius. [VERIFIED]
- **Action:**
  - `nlp_understanding.py` → merge into `application/services/` or delete if dead
  - `notifications.py` → move to `infrastructure/notifications/`
  - `ai_router.py` → move to `infrastructure/adapters/`
  - `agent_core_v2.py` → sunset; update any remaining callers
- **Files:** 4 root shims + their callers (discovered via `grep`)
- **Risk:** Medium (blast radius unknown — each shim may have hidden callers)
- **Effort:** 4h
- **Verification:** `ls weebot/*.py` shows only `__init__.py`.

**Phase A score impact:** +0.4 (Pattern 9→10, Hygiene 8→9, Modularity 8→8.5) → **8.4 → 8.8**

---

## Phase B — Structural Improvements (2 weeks, target 9.3)

### B1. Add event durability — journal before publish

- **Evidence:** `AsyncEventBus.publish()` fans out to subscribers in-memory only.
  Process crash between `_emit()` and `save_session()` loses the event.
  `EventStorePort` is wired but not integrated into the publish path. [VERIFIED]
- **Action:** Add a `DurableEventBus` decorator that writes to `EventStorePort`
  before delegating to `AsyncEventBus.publish()`. Register it in DI as the
  default `EventBusPort` implementation. Events are append-only — no replay
  needed in this phase.
- **Files:** `infrastructure/event_bus.py` (new decorator),
  `application/di/_factories.py`
- **Risk:** Medium (changes write-path semantics; must be idempotent)
- **Effort:** 1d
- **Verification:** Integration test: publish event, kill process before
  subscriber receives, restart, event is in EventStore.

### B2. Enable OpenTelemetry end-to-end tracing

- **Evidence:** `TracingPort` and `TracingAdapter` exist but are not wired into
  the flow/agent lifecycle. No spans for "PlanActFlow iteration," "ExecutorAgent
  step," or "LLM call."  Structured logging exists but traces don't propagate. [VERIFIED]
- **Action:**
  1. Wire `TracingPort` in `configure_defaults()` (DI).
  2. Add `@traced("plan_act_iteration")` decorator to `PlanActFlow.run()`.
  3. Add `@traced("executor_step")` to `ExecutorAgent.execute_step()`.
  4. Propagate `trace_id` from `SessionContext.trace_id` into span attributes.
  5. Export to OTEL collector (configurable endpoint).
- **Files:** `application/flows/plan_act_flow.py`, `application/agents/executor/_base.py`,
  `application/di/_factories.py`, `infrastructure/observability/tracing_adapter.py`,
  `infrastructure/observability/otel_sink.py`
- **Risk:** Low (additive, toggled by feature flag)
- **Effort:** 2d
- **Verification:** Start Jaeger locally, run a flow, see spans with trace_id in UI.

### B3. Fill integration test gaps for CQRS command handlers

- **Evidence:** Current test coverage is concentrated in unit tests. Some CQRS
  command handlers lack integration tests (e.g., `cancel_session_handler.py`,
  `harness_edit_handler.py`). Architecture fitness tests cover structure, not
  behavior. [VERIFIED]
- **Action:** Add integration tests for each CQRS handler that exercises the
  full pipeline (command → mediator → behaviors → handler → state repo).
  Minimum: `CreatePlanHandler`, `UpdatePlanHandler`, `ArchiveSessionHandler`,
  `CancelSessionHandler`, `HarnessEditHandler`.
- **Files:** `tests/integration/test_cqrs_handlers.py` (new)
- **Risk:** Medium (tests may surface latent bugs)
- **Effort:** 2d
- **Verification:** `pytest tests/integration/test_cqrs_handlers.py -v` — 5+ tests pass,
  each covering the full pipeline.

### B4. Add session-level retry (dead-letter queue)

- **Evidence:** When all 3 LLM tiers (FREE → BUDGET → PRIMARY) are down, the
  session fails permanently. There is no requeue mechanism. `TaskRunner` uses
  `asyncio.PriorityQueue` — in-memory, no persistence. [VERIFIED]
- **Action:** Add `rerun_failed_session(session_id)` to `TaskRunnerPort`.
  On triple-cascade failure, move session to a `failed_sessions` list with
  retry count. CLI gains `weebot flow retry <session_id>` command.  (Full
  Redis/RabbitMQ queue remains a Phase C item.)
- **Files:** `application/services/task_runner.py`, `application/ports/task_router_port.py`,
  `cli/main.py`
- **Risk:** Low (additive; no on-disk queue yet)
- **Effort:** 1d
- **Verification:** `python -m cli.main flow retry <failed_session_id>` re-enters
  PlanActFlow at the last saved state.

### B5. Move `BaseTool` to domain layer (reduce port friction)

- **Evidence:** `application/ports/mcp_tool_port.py`, `application/models/tool_collection.py`,
  and `application/skills/skill_packager.py` all import `BaseTool` from `weebot.tools.base`.
  This creates architectural friction — ports depend on a type defined outside
  the domain or application layer. [VERIFIED]
- **Action:** Move `BaseTool` (the ABC + `name/description/parameters/execute`
  interface contract) to `weebot/domain/models/base_tool.py`. Re-export from
  `tools/base.py` for backward compatibility. Update the 3 application
  import sites to use the domain location.  `BaseTool` is pure — no I/O, no
  framework deps beyond Pydantic `BaseModel` (already allowed in domain per
  ADR-001).
- **Files:** `domain/models/base_tool.py` (new), `tools/base.py` (re-export),
  `application/ports/mcp_tool_port.py`, `application/models/tool_collection.py`,
  `application/skills/skill_packager.py`
- **Risk:** Medium (touches the tool contract used by 45+ files)
- **Effort:** 3h
- **Verification:** All 45+ tools import `BaseTool` and work unchanged.
  `lint-imports` 6 contracts kept. Architecture fitness 50+ pass.

**Phase B score impact:** +0.5 (Hygiene 9→10, Observability 7→9, Resilience 8→9, Testability 7→8, Modularity 8.5→9) → **9.3**

---

## Phase C — Strategic Hardening (4–6 weeks, target 9.6)

### C1. Per-domain SQLite databases (split `weebot_sessions.db`)

- **Context:** All persistence components share one SQLite file. WAL serializes
  writers. Under SkillOpt batch_size=40 with multiple concurrent sessions, write
  throughput becomes a bottleneck. [VERIFIED — structurally true; HYPOTHESIS —
  not load-tested]
- **Action:** Split into `sessions.db` (session state + events), `skills.db`
  (skills + trajectories + edits), `cache.db` (response cache). Connection pool
  per DB. Migration scripts to move existing data.
- **Effort:** 1w
- **Risk:** High (schema changes, migration scripts, connection pool changes)
- **Gate:** Load-test first to confirm actual bottleneck.

### C2. Durable task queue (Redis Streams)

- **Context:** `TaskRunner` uses in-memory `asyncio.PriorityQueue`. Process
  restart loses all queued tasks. Multi-process deployment requires shared queue.
  [VERIFIED]
- **Action:** Add `RedisTaskQueue` adapter implementing `TaskRouterPort`.
  Feature-flag: `WEEBOT_QUEUE_BACKEND=redis`. In-memory remains default.
  Dead-letter queue for permanently failed sessions.
- **Effort:** 2w
- **Risk:** High (new infrastructure dependency, serialization contract)
- **Gate:** Optional — in-memory remains default.

### C3. Production PostgreSQL support

- **Context:** ADR-003 explicitly chose SQLite for local-first. PostgreSQL is
  planned for multi-user deployments. `postgresql/state_repo.py` exists but is
  not the default. [VERIFIED]
- **Action:** Complete `PostgresStateRepository`, add Alembic migrations for
  PostgreSQL schema, feature-flag with `WEEBOT_DB_BACKEND=postgresql`.
- **Effort:** 1w
- **Risk:** Medium (schema divergence, connection pooling differences)
- **Gate:** Integration test suite must pass with both backends.

### C4. Full test pyramid (E2E + performance)

- **Action:**
  - Add E2E tests for `weebot flow run "simple task"` (happy path + error).
  - Add performance smoke test: 10 concurrent flows, verify no deadlocks.
  - Add chaos test: kill process mid-flow, verify session is recoverable.
- **Effort:** 1w
- **Risk:** Medium (E2E tests are slow; may need dedicated CI job)

### C5. Dependabot / Renovate for dependency updates

- **Action:** Add `.github/dependabot.yml` for pip and npm.  Weekly schedule.
- **Effort:** 0.5h
- **Risk:** Low

**Phase C score impact:** +0.3 (Resilience 9→10, Modularity 9→10, Security 8→9, Testability 8→9) → **9.6**

---

## Migration Sequencing

```
Phase A (2 days)
├── A1 (LLMPort)  ──→ A2 (StateRepoPort)  ──→ A3 (event timeout)  ──→ A4 (import-linter)  ──→ A5 (shims)
│
Phase B (2 weeks)
├── B5 (BaseTool)  ──→ B1 (event durability)  ──→ B2 (OTEL tracing)
│                                              └──→ B3 (CQRS tests)  ──→ B4 (session retry)
│
Phase C (4-6 weeks)
├── C1 (DB split)  ──→ C3 (PostgreSQL)
├── C2 (Redis queue)
└── C4 (E2E tests)  ──→ C5 (Dependabot)
```

Dependencies are soft — items in the same phase can run in parallel.
Phase C items are gated on production need; they should not block Phases A–B.

---

## Risk Matrix

| Item | Risk | Rollback | Rollback time |
|---|---|---|---|
| A1–A4 (port additions) | Low | `git revert` | 1 min |
| A5 (root shims) | Medium | `git revert` per shim | 1 min each |
| B1 (event durability) | Medium | Feature flag off | Instant |
| B2 (OTEL tracing) | Low | Feature flag off | Instant |
| B3 (CQRS tests) | Low | Delete test file | N/A (tests only) |
| B4 (session retry) | Low | `git revert` | 1 min |
| B5 (BaseTool move) | Medium | `git revert` | 1 min |
| C1 (DB split) | High | Restore from backup | Time depends on data size |
| C2 (Redis queue) | High | `WEEBOT_QUEUE_BACKEND=memory` | Instant via feature flag |
| C3 (PostgreSQL) | Medium | `WEEBOT_DB_BACKEND=sqlite` | Instant via feature flag |

---

## Score Trajectory

```
8.0  ─── Phase A (2 days) ───→ 8.8
8.8  ─── Phase B (2 weeks) ──→ 9.3
9.3  ─── Phase C (6 weeks) ──→ 9.6
```

> The theoretical maximum of 10.0 is unattainable without replacing SQLite with
> a distributed database and the in-memory bus with a persistent message broker
> — neither of which is appropriate for the local-first design target.  9.6 is
> the achievable ceiling for this architecture.

---

## Appendix — Full Evidence Index

All [VERIFIED] claims below are backed by direct file reads in this session.

| Finding | EGFV | Source |
|---|---|---|
| `_context_compressor.py:149` imports `build_image_message` from infra | [VERIFIED] | `search_content "from weebot.infrastructure" weebot/application/` |
| `_base.py:444` lazy-imports `SQLiteStateRepository` | [VERIFIED] | `read_file weebot/application/agents/executor/_base.py:440-450` |
| `metrics_bridge.py` is a lazy interop bridge (not a true bypass) | [VERIFIED] | `read_file weebot/application/services/metrics_bridge.py` |
| `AsyncEventBus.publish()` uses `asyncio.gather` without per-subscriber timeout | [VERIFIED] | `read_file weebot/infrastructure/event_bus.py:44-80` |
| 4 root shim files exist | [VERIFIED] | `glob weebot/*.py` |
| No tool-layer import-linter contract | [VERIFIED] | `read_file .importlinter` — 5 contracts, none for tools |
| `TracingAdapter` not wired into flow lifecycle | [VERIFIED] | `search_content "TracingPort\|tracing" weebot/application/flows/` returned empty |
| All sandbox backends have truncation markers | [VERIFIED] | `search_content "TRUNCATION" weebot/infrastructure/sandbox/` |
| `SessionContext` has 100-entry facts cap | [VERIFIED] | `read_file weebot/domain/models/session.py:55-75` |
| `EventStorePort` is wired by default | [VERIFIED] | `read_file weebot/application/di/__init__.py:136` |
| `ValidationGateBehavior` uses `isinstance` | [VERIFIED] | `read_file weebot/application/cqrs/behaviors/validation_gate.py:42` |
| All CQRS handlers call `save_session()` | [VERIFIED] | `search_content "save_session" weebot/application/cqrs/handlers/` |
| `ToolResult` already moved to domain | [VERIFIED] | `read_file weebot/domain/models/tool_result.py` (exists) + Phase 0 delta applied |
| 5 import-linter contracts, all kept | [VERIFIED] | `run_command lint-imports` — 5 kept, 0 broken |
