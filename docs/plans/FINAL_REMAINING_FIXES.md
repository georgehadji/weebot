# Remaining Architectural Debt — Implementation Plan

**Source:** `docs/ARCHITECTURE_AUDIT.md`, current codebase state as of commit `6baa5ab`  
**Estimated effort:** 5–7 days across 3 workstreams

---

## What's Already Done (90 items across 5 sessions)

| Phase | Scope | Commits |
|-------|-------|---------|
| A+B | Domain purity, importlinter, mediator extraction, CQRS persistence, ToolCollection promotion, EventStore wiring, scoped mediators, app service TYPE_CHECKING | `25bce26` |
| 1 | Typed SessionContext, facts eviction, MemoryPort, PowerShell async cleanup | `c6deb23` |
| 2 | Emit lock, max_iterations, prompt externalization, ToolRepositoryPort wiring, session retry, MemoryFacade | `a15246f` |
| 3a | Root shim elimination (32→7 files), ToolConfig DI, state map, importlinter CI, circular import test | `9ef935f` |
| 3b | DI validation, task queue port, un-skip circular import test | `6baa5ab` |

---

## Remaining Items — Prioritized

### Workstream A — Tool sqlite3 Migration (~2 days)

**Problem:** 3 tools (`knowledge_tool.py`, `product_tool.py`, `video_ingest_tool.py`) bypass the existing `ToolRepositoryPort` and call `sqlite3` directly. The port + adapter exist but no production code calls through them. `test_tools_no_direct_db` tolerates them via a `known_exception_tools` carve-out.

#### A1: Audit tool DB operations (0.5 day)

Read all sqlite3 calls in each tool and map them to the `ToolRepositoryPort` interface methods.

| Tool | sqlite3 calls | Tables used |
|------|--------------|-------------|
| `knowledge_tool.py` | ~20 (CREATE TABLE IF NOT EXISTS, INSERT, SELECT FTS5, DELETE) | `knowledge_notes`, `knowledge_fts` |
| `product_tool.py` | ~19 (CREATE TABLE IF NOT EXISTS, INSERT, SELECT, UPDATE, DELETE) | `product_requirements` |
| `video_ingest_tool.py` | ~18 (CREATE TABLE IF NOT EXISTS, INSERT, SELECT, UPDATE) | `video_sources` |

**Decision gate:** After audit, decide whether to:
- **Widen the port** — add missing methods to `ToolRepositoryPort` + `SQLiteToolRepository`, then wire in each tool
- **Keep the carve-out** — accept the exception as permanent debt (the tools are low-traffic and the pattern is stable)

**Recommendation:** Widen the port. The adapter already manages the DB connection; adding the missing methods is 1–2 lines each.

#### A2: Extend ToolRepositoryPort (0.5 day)

| Step | File | Action |
|------|------|--------|
| A2.1 | `application/ports/tool_repository_port.py` | Add `search_notes(keywords, limit) -> list[dict]`, `update_note(note_id, content) -> bool`, `list_requirements(project) -> list[dict]`, `update_requirement(req_id, updates) -> bool`, `list_video_sources(status) -> list[dict]`, `update_video_source(url, metadata) -> bool` |
| A2.2 | `infrastructure/persistence/sqlite_tool_repo.py` | Implement all new methods, reusing existing `_connect()` and WAL pragma |

#### A3: Wire tools to use the port (0.5 day)

| Step | File | Action |
|------|------|--------|
| A3.1 | `tools/knowledge_tool.py` | Add `_repo: ToolRepositoryPort` PrivateAttr. Accept via constructor or `set_repo()`. Replace all `sqlite3.connect()` + SQL calls with port method calls. |
| A3.2 | `tools/product_tool.py` | Same pattern |
| A3.3 | `tools/video_ingest_tool.py` | Same pattern |
| A3.4 | `tests/unit/test_architecture_fitness.py` | Remove `known_exception_tools` block — all 3 tools now comply |
| A3.5 | `.importlinter` | Remove `weebot.tools.knowledge_tool -> sqlite3` (and product, video_ingest) from `ignore_imports` in `tools-no-db` contract |

#### A4: Wire in DI and test (0.5 day)

| Step | File | Action |
|------|------|--------|
| A4.1 | `application/di.py` | Pass `ToolRepositoryPort` to each tool in factory methods |
| A4.2 | `tools/tool_registry.py` | Pass `tool_repo` when constructing these 3 tools |
| A4.3 | Run test suite | `pytest tests/unit/ -v` — verify no regression |

**Verification:**
```bash
grep -rn "import sqlite3" weebot/tools/ --include="*.py"
# Expected: 0 results
pytest tests/unit/test_architecture_fitness.py::test_tools_no_direct_db -v
# Expected: PASSED
```

---

### Workstream B — PowerShellTool Dead Code Removal (~0.25 day)

**Problem:** `PowerShellBaseTool.execute()` has a fallback block after the `except` that is unreachable — every code path before it returns. The indentation is also wrong (at class level, not inside the method).

#### B1: Remove dead-code fallback

| Step | File | Action |
|------|------|--------|
| B1.1 | `tools/powershell_tool.py:281-289` | Delete the 8-line fallback block starting with `# Fallback: kept for backward compatibility` through the final `except` |
| B1.2 | Verify | `python -c "from weebot.tools.powershell_tool import PowerShellBaseTool; print('OK')"` |

---

### Workstream C — Legacy Root File Cleanup (~3–5 days)

**Problem:** 6 legacy modules remain at `weebot/` root. These are full modules (not deprecation shims) with their own functionality. Each needs individual migration or freeze documentation.

| File | Lines | Description | Recommendation |
|------|-------|-------------|----------------|
| `agent_core_v2.py` | ~1,500 | Pre-clean-arch agent runner | **FREEZE** — document as superseded by `PlanActFlow`/`ChatFlow` |
| `agent_selection.py` | ~400 | Agent role routing | **ASSESS** — may overlap with `RoleBasedToolRegistry` |
| `failure_recovery.py` | ~426 | Auto-retry on failure | **MIGRATE** — core logic overlaps with `TaskRunner` retry (added in R9) |
| `state_coordinator.py` | ~800 | Session lifecycle manager | **FREEZE** — superseded by `StateRepositoryPort` + `TaskRunner` |
| `state_manager.py` | ~641 | Pre-clean-arch session state | **FREEZE** — superseded by `Session` domain model |
| `tray.py` | ~300 | System tray icon | **MIGRATE** or move to `interfaces/` |

#### C1: Audit & classify (0.5 day)

| Step | Action |
|------|--------|
| C1.1 | For each file: `grep -rn "from weebot.<file>" weebot/ --include="*.py"` to find all importers |
| C1.2 | Classify each as **FREEZE** (no migration, no new features, target sunset 2027) or **MIGRATE** (functionality has a clean-arch home) |

#### C2: Migrate failure_recovery.py (~1.5 days)

**Problem:** `failure_recovery.py` implements auto-retry logic for task failures. The `TaskRunner` already has basic retry (R9). The `failure_recovery` module's retry policies, circuit breakers, and recovery strategies should be consolidated.

| Step | File | Action |
|------|------|--------|
| C2.1 | `application/services/failure_recovery.py` | New: extract retry policy logic from `failure_recovery.py` into application service |
| C2.2 | `application/ports/recovery_port.py` | New: `RecoveryPort` ABC for pluggable failure recovery |
| C2.3 | `application/services/task_runner.py` | Wire `RecoveryPort` into the retry path |
| C2.4 | `weebot/failure_recovery.py` | Replace body with `from weebot.application.services.failure_recovery import *` deprecation shim |
| C2.5 | Bump sunset | Set `failure_recovery.py` sunset to 2027-03-01 |

#### C3: Freeze remaining 5 files (0.5 day)

| Step | File | Action |
|------|------|--------|
| C3.1 | `agent_core_v2.py` | Add `# LEGACY — Frozen. No new features.` header. Update `test_no_flat_files_at_root` to include it as allowed. |
| C3.2 | `agent_selection.py` | Same |
| C3.3 | `state_coordinator.py` | Same |
| C3.4 | `state_manager.py` | Same |
| C3.5 | `tray.py` | Same — or move to `weebot/interfaces/tray.py` if it's actively used |

#### C4: Update fitness test allowed_files (0.25 day)

| Step | File | Action |
|------|------|--------|
| C4.1 | `tests/unit/test_architecture_fitness.py` | Update `allowed_files` to reflect final state. Add a `test_no_new_root_files` that fails if any `.py` file appears at `weebot/` root outside the frozen list. |

---

## Dependency Order

```
Workstream A (Tool sqlite3) ── independent of B and C
Workstream B (PS dead code) ── independent of A and C
Workstream C (Legacy files) ── independent of A and B
```

All three workstreams are independent and can run in parallel.

---

## Risk Register

| # | Risk | Probability | Mitigation |
|---|------|------------|------------|
| R-A | `SQLiteToolRepository` schema doesn't match `knowledge_tool`'s internal schema | Medium | Audit step A1 catches schema differences before wiring |
| R-B | Removing fallback code in PowerShellBaseTool breaks edge case | Low | The code is unreachable by construction; remove with confidence |
| R-C | `failure_recovery.py` has hidden importers in test files | Medium | Audit step C1.1 catches all importers before migration |
| R-D | Legacy file freeze confuses developers who expect active development | Low | Add clear LEGACY header with sunset date and migration path pointers |

---

## Verification Gates

### After Workstream A
```bash
grep -rn "import sqlite3" weebot/tools/ --include="*.py"  # → 0
pytest tests/unit/test_architecture_fitness.py::test_tools_no_direct_db -v  # → PASSED
```

### After Workstream B
```bash
python -c "from weebot.tools.powershell_tool import PowerShellBaseTool; print('OK')"
```

### After Workstream C
```bash
ls weebot/*.py | wc -l  # → 7 (unchanged, but 1 migrated to deprecation shim)
pytest tests/unit/test_architecture_fitness.py::test_no_flat_files_at_root -v  # → PASSED
pytest tests/unit/ -v -q  # → all pass
```
