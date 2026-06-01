# Remaining Architecture Audit Fixes — Implementation Plan

**Source:** `docs/ARCHITECTURE_AUDIT.md` Sections 4–7 (findings not yet addressed)  
**Cross-referenced with:** `ARCHITECTURE_REMEDIATION_PLAN.md`, `ARCHITECTURE_EXCELLENCE_PLAN.md`, `ARCHITECTURE_ENHANCEMENT_PLAN.md`  
**Date:** 2026-06-01  
**Completed (Phase A+B):** 10/10 steps done — see commit `25bce26`

---

## What's Already Done (do NOT re-implement)

| Audit Finding | Resolution | Commit |
|---------------|-----------|--------|
| A1–A4, B1–B5 | All 10 Phase A+B steps | `25bce26` |
| `EventStore` inherits `EventStorePort` | Already true on disk | Prior work |
| `SavePolicyBehavior` exists + registered | `behaviors/save_policy.py` wired in `build_mediator()` | Prior work |
| Policy-error-loop detection (`_MAX_SAME_ERROR_CLASS`) | Already in `executor.py` | Prior work |

---

## Remaining Findings — Prioritized by Severity

### CRITICAL / HIGH (Production Safety & Correctness)

| ID | Finding | Audit § | Score Impact |
|----|---------|---------|--------------|
| **R1** | PowerShellTool sync `subprocess.run()` blocks event loop | 5.4 | Async Hygiene +1 |
| **R2** | `bash_tool.py` timeout coercion bug — string timeout not coerced to `float` | 5.4 | Error Handling +1 |
| **R3** | 64 KB sandbox output cap silently truncates with no marker to agent | 5.4 | State Mgmt +1 |
| **R4** | `PersistentMemoryTool` writes flat `.md` files via hardcoded `~/.weebot/memory/` path — bypasses all ports | 5.6 | Security +1 |
| **R5** | `Session.context` is untyped `Dict[str, Any]` with magic-string keys (`skill_name`, `_original_task`, `facts`) | 5.5 | State Mgmt +1 |
| **R6** | `Session.context["facts"]` grows unboundedly — no eviction policy | 5.5 | State Mgmt +1 |

### MEDIUM (Structural Integrity & Maintainability)

| ID | Finding | Audit § | Score Impact |
|----|---------|---------|--------------|
| **R7** | Dead `ToolRepositoryPort` — ABC + adapter exist but zero callers; 3 tools bypass it with direct `sqlite3` | 6.7 | Dependency Direction +1 |
| **R8** | 4 overlapping memory systems with no formal interface: `Session._memory_index`, `WorkingMemory`/`EpisodicMemory`, `ConversationCompressor`, `PersistentMemoryTool` | 5.6 | State Mgmt +1 |
| **R9** | No end-to-end retry at session level — all 3 LLM tiers down → session fails permanently | 5.7 | Error Handling +1 |
| **R10** | `PlanActFlow._emit()` has no asyncio lock guarding concurrent `_session` mutation (event bus callback + flow loop) | 4.4 | Async Hygiene +1 |
| **R11** | `EXECUTOR_SYSTEM_PROMPT` is a 50+ line module-level string constant — no versioning, no runtime override without subclassing | 4.5 | Maintainability +1 |
| **R12** | `max_iterations = 50` hardcoded in `PlanActFlow.run()` — not configurable via constructor | 5.2 | Maintainability +1 |

### LOW (Long-Term Evolution — Phase C items)

| ID | Finding | Audit § | Effort |
|----|---------|---------|--------|
| **R13** | Eliminate root-level legacy shim layer (18 remaining shims) | C1 | 3–5 days |
| **R14** | Split shared SQLite into per-domain databases | C2 | 5–10 days |
| **R15** | Introduce durable task queue (Redis Streams / RabbitMQ) | C3 | 5–10 days |
| **R16** | Complete ToolConfig DI migration for remaining 4 tools | C5 | 1–2 days |
| **R17** | Enable `importlinter` in CI as a merge gate | C6 | 0.5 day |
| **R18** | `PlanActFlow.set_state()` hardcodes all concrete state classes in a dict — fragile to new states | 4.5 | 0.5 day |
| **R19** | `di.Container` resolves 30+ singletons — factory method signature changes break at runtime | 4.5 | 2 days |
| **R20** | `test_no_circular_imports` is `@pytest.mark.skip` in CI — transitive ring via root shims undetected | 4.1 | 1 day |

---

## Implementation Phases

### Phase 1 — Production Safety (Week 1, ~3 days) — R1–R6

> Fix the HIGH findings that can cause silent data loss, event-loop stalls, or security bypasses.

#### R1: PowerShellTool Async Conversion (0.5 day)

**Problem:** `PowerShellTool` inherits from `langchain.tools.BaseTool` which has a synchronous `_run()` wrapper. The subprocess blocks the event loop.

**Fix:** Replace `subprocess.run()` with `asyncio.create_subprocess_exec()` in the PowerShell execution path.

| Step | File | Action |
|------|------|--------|
| R1.1 | `tools/powershell_tool.py` | Replace `subprocess.run()` calls with `asyncio.create_subprocess_exec()` |
| R1.2 | `tools/powershell_tool.py` | Wrap all `_run()` → `_arun()` delegation to ensure async path is always taken |
| R1.3 | `tests/unit/test_powershell_async.py` | New test: verify `asyncio.wait_for(tool.execute(...), timeout=0.5)` works without event-loop stall |

**Verification:**
```bash
grep -rn "subprocess.run" weebot/tools/powershell_tool.py
# Expected: 0 results
```

#### R2: BashTool Timeout Coercion Fix (0.25 day)

**Problem:** `BashTool` does not coerce `timeout` arg from string to `float` — undefined behavior (documented in `execution-reliability-fix-plan.md` Fix 4).

**Fix:** Explicit `float(timeout)` coercion in the tool's `execute()` method.

| Step | File | Action |
|------|------|--------|
| R2.1 | `tools/bash_tool.py` | Add `timeout = float(timeout) if timeout is not None else 60.0` at top of execute |
| R2.2 | `tests/unit/test_bash_tool.py` | Add test: `execute("echo hi", timeout="30")` → must not raise TypeError |

#### R3: Sandbox Output Truncation Marker (0.25 day)

**Problem:** 64 KB cap (`sandbox_max_output_bytes=65536`) silently truncates. The agent has no way to know output was truncated.

**Fix:** Already partially fixed in `ToolCollection` (truncation metadata added). Ensure the marker is always present and visible to the agent.

| Step | File | Action |
|------|------|--------|
| R3.1 | `tools/bash_tool.py` | After sandbox output, if len > MAX, append `[TRUNCATED: N bytes omitted]` |
| R3.2 | `tools/python_tool.py` | Same |
| R3.3 | `tools/powershell_tool.py` | Same |

#### R4: PersistentMemoryTool Port Adapter (1 day)

**Problem:** `PersistentMemoryTool` writes directly to `~/.weebot/memory/{AGENT,USER}.md` via `Path.write_text()`. No port abstraction — not reproducible across deployments.

**Fix:** Create `MemoryPort` ABC with `read()`/`write()` methods. Implement a `FileSystemMemoryAdapter`. Inject via constructor.

| Step | File | Action |
|------|------|--------|
| R4.1 | `application/ports/memory_port.py` | New: `MemoryPort(ABC)` with `async read(file: str) -> str` and `async write(file: str, content: str) -> None` |
| R4.2 | `infrastructure/persistence/filesystem_memory.py` | New: `FileSystemMemoryAdapter(MemoryPort)` — wraps current `~/.weebot/memory/` logic |
| R4.3 | `tools/persistent_memory.py` | Change `PersistentMemoryTool.__init__` to accept `memory: MemoryPort`. Default to `FileSystemMemoryAdapter()` for backward compat. Replace `MEMORY_DIR`/`_memory_path`/`_save_entries`/`_load_entries` with port calls. |
| R4.4 | `application/di.py` | Register `MemoryPort → FileSystemMemoryAdapter` in `configure_defaults()` |
| R4.5 | `tests/unit/test_persistent_memory.py` | Test with mock `MemoryPort` — verify read/write flow without touching real filesystem |

#### R5: Typed SessionContext (0.5 day)

**Problem:** `Session.context` is `Dict[str, Any]`. Keys `skill_name`, `skill_content`, `_original_task`, `facts`, `archived`, `archived_at`, `archive_ttl_days` are magic strings with no schema.

**Fix:** Define `SessionContext(BaseModel)` with explicit typed fields. Migrate all access sites.

| Step | File | Action |
|------|------|--------|
| R5.1 | `domain/models/session.py` | Add `SessionContext(BaseModel)` with typed fields: `skill_name: str`, `skill_content: str`, `_original_task: str`, `facts: Dict[str, Any]`, `archived: bool`, `archived_at: Optional[str]`, `archive_ttl_days: int` |
| R5.2 | `domain/models/session.py` | Change `Session.context: Dict[str, Any]` → `Session.context: SessionContext` |
| R5.3 | All access sites | Replace `session.context.get("skill_name")` with `session.context.skill_name`. Audit: `search_content "context\["` or `context.get(` across weebot/. |
| R5.4 | Migration | Add Pydantic validator that reads old dict-format context on load and converts to typed model |

#### R6: Facts Eviction Policy (0.25 day)

**Problem:** `session.context["facts"]` grows unboundedly — no eviction, no size limit.

**Fix:** Add a `max_facts: int = 100` cap with LRU eviction in `Session.add_event()` or in the `facts` property.

| Step | File | Action |
|------|------|--------|
| R6.1 | `domain/models/session.py` | In `model_validator` or post-init, enforce `len(self.context.facts) <= MAX_FACTS`. If exceeding, keep newest `MAX_FACTS` by key insertion order. |

---

### Phase 2 — Structural Integrity (Week 2, ~4 days) — R7–R12

> Fix the MEDIUM findings that erode maintainability and architectural clarity.

#### R7: Wire or Delete ToolRepositoryPort (0.5 day)

**Problem:** `application/ports/tool_repository_port.py` defines a `ToolRepositoryPort` ABC and an implementing adapter exists, but **zero application code calls through it**. Three tools (`knowledge_tool`, `product_tool`, `video_ingest_tool`) use direct `sqlite3` instead.

**Decision:** Wire the port in the 3 tools OR delete the port as premature abstraction. Recommendation: **wire it** — it's the correct pattern and the adapter already exists.

| Step | File | Action |
|------|------|--------|
| R7.1 | `tools/knowledge_tool.py` | Replace direct `sqlite3` calls with `self._tool_repo.save()/load()` via `ToolRepositoryPort` |
| R7.2 | `tools/product_tool.py` | Same |
| R7.3 | `tools/video_ingest_tool.py` | Same |
| R7.4 | `application/di.py` | Register `ToolRepositoryPort` binding |
| R7.5 | `.importlinter` | Remove the `tools-no-db` contract exceptions for these 3 tools |

#### R8: Memory System Consolidation (1 day)

**Problem:** 4 overlapping memory systems with no formal interface between them. An agent doesn't know what's in `SessionMemory` vs `WorkingMemory` vs `PersistentMemoryTool`.

**Fix:** Document the boundaries and add a `MemoryFacade` that routes reads across all systems.

| Step | File | Action |
|------|------|--------|
| R8.1 | `docs/MEMORY_ARCHITECTURE.md` | New doc: describe each system's scope, lifecycle, and access pattern |
| R8.2 | `application/services/memory_facade.py` | New: `MemoryFacade` — unified `recall(query)` method that searches across `Session._memory_index`, `WorkingMemory`, `EpisodicMemory`, and `PersistentMemoryTool` |
| R8.3 | `application/di.py` | Register `MemoryFacade` binding |
| R8.4 | `application/agents/executor.py` | Inject `MemoryFacade` — use `facade.recall()` instead of only `self._facts` |

#### R9: Session-Level Retry via TaskRunner (0.5 day)

**Problem:** All 3 LLM tiers down → session fails permanently with no requeue.

**Fix:** Add `max_session_retries` to `TaskRunner`. On failure, if retries remain, requeue the session with a backoff delay.

| Step | File | Action |
|------|------|--------|
| R9.1 | `application/services/task_runner.py` | Add `max_session_retries: int = 2` parameter. On session failure, if `retries < max`, requeue with `asyncio.sleep(backoff)`. |
| R9.2 | `tests/unit/test_task_runner_retry.py` | New test: mock LLM to fail 3 times → verify session retried then marked FAILED |

#### R10: asyncio Lock for _emit() (0.25 day)

**Problem:** `PlanActFlow._emit()` does `self._session = self._session.add_event(event)` followed by `save_session()`. If two coroutines emit simultaneously (event bus callback + flow loop), one write overwrites the other's intermediate session state.

**Fix:** Guard `_emit()` with `asyncio.Lock`.

| Step | File | Action |
|------|------|--------|
| R10.1 | `application/flows/plan_act_flow.py` | Add `self._emit_lock = asyncio.Lock()` in `__init__`. Wrap `_emit()` body in `async with self._emit_lock:`. |
| R10.2 | `application/flows/chat_flow.py` | Same pattern |

#### R11: EXECUTOR_SYSTEM_PROMPT as Configurable Resource (0.5 day)

**Problem:** 50+ line string constant embedded at module level. No versioning, no override without subclassing.

**Fix:** Move to a template file, load at runtime, support overrides via system prompt variables.

| Step | File | Action |
|------|------|--------|
| R11.1 | `application/agents/executor.py` | Extract `EXECUTOR_SYSTEM_PROMPT` → `weebot/config/prompts/executor_system.txt` |
| R11.2 | `application/agents/executor.py` | Load via `importlib.resources` or `Path.read_text()`. Add `system_prompt_override: Optional[str]` constructor param. |
| R11.3 | `application/agents/executor.py` | Support `{skill_prompt}`, `{persistent_memory}`, `{tool_list}` template variables |

#### R12: Configurable max_iterations (0.25 day)

**Problem:** `max_iterations = 50` hardcoded in `PlanActFlow.run()` line 170.

| Step | File | Action |
|------|------|--------|
| R12.1 | `application/flows/plan_act_flow.py` | Add `max_iterations: int = 50` to `__init__` signature. Replace hardcoded constant. |
| R12.2 | `application/di.py` | Pass `max_iterations` from config when building flows |

---

### Phase 3 — Long-Term Evolution (Weeks 3–5, ~15 days) — R13–R20

> Phase C items from the audit — these are infrastructure-level changes.

#### R13: Root Shim Elimination (3–5 days)

**Audit C1.** 18 remaining root-level shims with deprecation warnings.

| Step | Action |
|------|--------|
| R13.1 | For each shim: `grep -rn "from weebot.<shim>" weebot/ --include="*.py"`. If 0 callers → delete. |
| R13.2 | For shims with callers: migrate callers to import from `application/services/` directly, then delete shim. |
| R13.3 | Add CI gate: `test_no_new_shim_imports` in fitness tests |

#### R14: Per-Domain Database Split (5–10 days)

**Audit C2.** Separate `weebot_sessions.db` into `sessions.db`, `skills.db`, `cache.db`.

| Step | Action |
|------|--------|
| R14.1 | Create migration scripts for each domain |
| R14.2 | Update `configure_defaults()` to accept per-domain db_path kwargs |
| R14.3 | For production scale: add PostgreSQL + `asyncpg` support behind a feature flag |

#### R15: Durable Task Queue (5–10 days)

**Audit C3.** Replace `TaskRunner`'s in-memory `asyncio.PriorityQueue` with Redis Streams or RabbitMQ.

| Step | Action |
|------|--------|
| R15.1 | Create `TaskQueuePort` ABC in `application/ports/` |
| R15.2 | Implement `InMemoryTaskQueue` (current behavior) and `RedisTaskQueue` adapters |
| R15.3 | Wire via DI; default to in-memory for dev, Redis for prod |
| R15.4 | Add dead-letter queue for failed sessions |

#### R16: ToolConfig DI Migration (1–2 days)

**Audit C5.** Complete migration of all tools to receive config via constructor injection.

| Step | File | Action |
|------|------|--------|
| R16.1 | `tools/file_editor.py` | Add `set_config(ToolConfig)` method |
| R16.2 | `tools/powershell_tool.py` | Add `_tool_config` PrivateAttr; replace `_get_settings()` |
| R16.3 | `tools/bash_tool.py` | Remove legacy `_get_settings()` fallback — config-only |
| R16.4 | `tools/python_tool.py` | Same |
| R16.5 | `tests/unit/test_architecture_fitness.py` | Remove all `settings_exceptions` — 0 exceptions after migration |

#### R17: Importlinter CI Merge Gate (0.5 day)

**Audit C6.** Run `lint-imports` as a blocking CI step.

| Step | Action |
|------|--------|
| R17.1 | `.github/workflows/architecture.yml` | Add `lint-imports` job |
| R17.2 | Fix any remaining contract violations |
| R17.3 | Enable branch protection rule blocking merge on failure |

#### R18: State Map Dynamic Registration (0.5 day)

**Audit 4.5.** `PlanActFlow.set_state()` hardcodes all state classes in a dict. Adding a new state requires modifying this method.

| Step | File | Action |
|------|------|--------|
| R18.1 | `application/flows/plan_act_flow.py` | Replace `state_map` dict with a class attribute on each `FlowState` subclass (`status: AgentStatus`). Use `type(state).status` instead of dict lookup. |

#### R19: DI Container Refactor (2 days)

**Audit 4.5.** `di.Container` resolves 30+ singletons with string-keyed registrations. Factory method signature changes break at runtime.

| Step | Action |
|------|--------|
| R19.1 | Replace string-keyed registrations (`"activity_stream"`, `"response_cache"`) with proper port types |
| R19.2 | Add `Container.resolve_all()` for batch validation at startup |
| R19.3 | Add startup self-check: resolve every registered port, fail fast if any factory raises |

#### R20: Un-skip Circular Import Test (1 day)

**Audit 4.1.** `test_no_circular_imports` is `@pytest.mark.skip`. The transitive ring via root shims is undetected.

| Step | Action |
|------|--------|
| R20.1 | Un-skip the test. Run it. Fix any circular imports found. |
| R20.2 | If the test is too slow for CI, add it as a nightly job instead of skipping entirely |

---

## Dependency Order

```
Phase 1 (Production Safety)
  R1 (PS async) ──┐
  R2 (timeout)  ──┤
  R3 (truncation)─┤ All independent — can run in parallel
  R4 (memory port)┤
  R5 (typed ctx)──┤
  R6 (facts cap) ─┘
        ↓
Phase 2 (Structural Integrity)
  R5 → R8 (memory facade depends on typed context)
  R7 (tool repo), R9 (retry), R10 (emit lock), R11 (prompt), R12 (max iter) — independent
        ↓
Phase 3 (Long-Term Evolution)
  R13 (shims) → R17 (importlinter CI) → R20 (circular import test)
  R14 (DB split), R15 (task queue) — independent heavy lifts
  R16 (ToolConfig), R18 (state map), R19 (DI refactor) — independent
```

---

## Score Trajectory Projection

| Dimension | Current (Post A+B) | After Phase 1 | After Phase 2 | After Phase 3 |
|-----------|-------------------|---------------|---------------|---------------|
| Domain Purity | 10 | 10 | 10 | 10 |
| CQRS Enforcement | 9 | 9 | 9 | 10 |
| Dependency Direction | 8 | 8 | 9 | 10 |
| Security Boundary Integrity | 7 | 8 | 9 | 9 |
| Observability | 7 | 7 | 8 | 9 |
| Test Architecture | 8 | 8 | 9 | 10 |
| DI / IoC Consistency | 8 | 8 | 9 | 10 |
| State Management | 7 | 8 | 9 | 10 |
| Async Hygiene | 7 | 8 | 9 | 9 |
| Error Handling | 7 | 8 | 9 | 9 |
| **Weighted Average** | **~7.8** | **~8.2** | **~9.0** | **~9.6** |

---

## Risk Register

| # | Risk | Probability | Mitigation |
|---|------|------------|------------|
| RR1 | PowerShellTool async conversion changes subprocess behavior | Low | Identical semantics — `create_subprocess_exec` wraps the same OS call |
| RR2 | `SessionContext` migration breaks serialized sessions in DB | Medium | Add Pydantic validator that auto-migrates dict-format context on load |
| RR3 | `PersistentMemoryTool` port adapter changes file format | Low | The port contract reads/writes strings — the §-delimited format is unchanged |
| RR4 | `MemoryFacade` adds latency to every agent step | Medium | Make facade optional; only activate when >1 memory system is configured |
| RR5 | `asyncio.Lock` in `_emit()` serializes parallel event emissions | Low | `_emit()` is already serial in practice — the lock just makes it explicit |
| RR6 | Root shim deletion unearths hidden importers in rarely-used code paths | Medium | Audit step R13.1 catches all importers before deletion |
| RR7 | DB split requires downtime for migration | High | Run dual-write for 1 release cycle before cutting over reads |

---

## Verification Gates (per phase)

### Phase 1 Gate
```bash
grep -rn "subprocess.run" weebot/tools/powershell_tool.py  # → 0
python -c "from weebot.application.ports.memory_port import MemoryPort; print('OK')"
pytest tests/unit/test_persistent_memory.py tests/unit/test_bash_tool.py -v
```

### Phase 2 Gate
```bash
grep -rn 'context\["' weebot/application/ --include="*.py"  # → 0 (all migrated to typed)
grep -rn "sqlite3" weebot/tools/ --include="*.py" | grep -v "test_"  # → 0 (except tool_repo adapter)
pytest tests/unit/test_task_runner_retry.py -v
```

### Phase 3 Gate
```bash
ls weebot/*.py | wc -l  # → reduced from 18 to 0 (all shims deleted)
pytest tests/unit/test_architecture_fitness.py -v  # → 25+ tests, 0 skipped
lint-imports  # → passes clean
```
