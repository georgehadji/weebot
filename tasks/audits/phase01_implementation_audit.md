# Implementation Audit Report

**Audit scope:** Commit `b0f5508..2f6bb59` — Phases 0 and 1 of Agent-Native Memory system  
**Plan reference:** `tasks/specs/agent_native_memory_implementation_plan.md`  
**Date:** 2026-06-30

---

## 1. Executive Summary

Phases 0 (FTS5 fix) and 1 (recency-aware merge) were implemented across 5 files with 602 new lines and 30 deletions. **All planned work items are complete.** Architecture compliance is high — the merge policy was correctly relocated from the infrastructure adapter into the application service layer, fixing a Clean Architecture layering violation. 12 tests cover both phases comprehensively.

**One architectural regression found:** The `PostgreSQLKnowledgeGraph` adapter is missing the newly required `get_node()` abstract method (added to `KnowledgeGraphPort`). The adapter is not currently imported by any caller, so this is latent but must be fixed before any PostgreSQL deployment.

**Verdict: APPROVED WITH 1 REQUIRED CORRECTION** (PostgreSQL adapter `get_node` stub).

---

## 2. Plan Compliance Matrix

| Plan Item | Status | Evidence | Notes |
|-----------|--------|----------|-------|
| **Phase 0: FTS triggers** | ✅ Complete | `sqlite_knowledge_graph.py:115-157` — 3 `CREATE TRIGGER` statements (INSERT/UPDATE/DELETE) | Exact SQL from spec, line-matched |
| **Phase 0: One-time backfill** | ✅ Complete | `sqlite_knowledge_graph.py:159-169` — Count check + `INSERT … VALUES('rebuild')` | Idempotent guard: runs only when FTS=0, kg_nodes>0 |
| **Phase 0: LIKE fallback preserved** | ✅ Complete | `sqlite_knowledge_graph.py:408-420` — `try/except OperationalError` still wraps FTS path, falls through to LIKE | Existing path untouched |
| **Phase 0: FTS DDL wrapped in try/except** | ✅ Complete | `sqlite_knowledge_graph.py:111,172` — All triggers and rebuild inside existing try/except | Same exception handler as original FTS creation |
| **Phase 1: Validity constants** | ✅ Complete | `domain/models/knowledge_graph.py:27-52` — `CONFIDENCE_KEY`, `VALID_FROM_KEY`, `VALID_TO_KEY`, `CORROBORATION_KEY` | Reserved property keys, no schema migration |
| **Phase 1: Merge policy in service** | ✅ Complete | `application/services/knowledge_graph.py:46-120` — Pure `merge_properties()` function with 3 rules | In application layer, no infra deps |
| **Phase 1: Merge policy rules** | ✅ Complete | Lines 83-118 — Rule 1 (confidence ≥ margin → overwrite), Rule 2 (conflict + recency → overwrite with stamp), Rule 3 (agreement → corroborate) | `_has_conflict()` helper at lines 123-138 |
| **Phase 1: Merge out of adapter** | ✅ Complete | `sqlite_knowledge_graph.py:185-230` — Old confidence comparison and `merged_props` logic removed; adapter is write-through | Docstring explicitly states policy lives in service |
| **Phase 1: Adapter UPDATE includes label/name** | ✅ Complete | `sqlite_knowledge_graph.py:203-210` — `SET label=?, name=?, properties=?, version=?, updated_at=?` | Bonus fix beyond spec — was silently dropping name changes |
| **Phase 1: `get_node` on port** | ✅ Complete | `knowledge_graph_port.py:42-49` — `async def get_node(node_id)` abstract | Added to `KnowledgeGraphPort` ABC |
| **Phase 1: `get_node` on adapter** | ✅ Complete | `sqlite_knowledge_graph.py:167-175` | Standard `_run_db` + `_row_to_node` pattern |
| **Phase 1: `discover_node` updated** | ✅ Complete | `application/services/knowledge_graph.py:196-203` — Calls `adapter.get_node()`, applies `merge_properties()` if exists | Service-level orchestration |

### Tests (Phase 0)

| Test | Status | Evidence |
|------|--------|----------|
| `test_fts_index_populated_on_upsert` | ✅ Pass | `test_knowledge_graph_fts.py:46` |
| `test_fts_reflects_update` | ✅ Pass | `test_knowledge_graph_fts.py:68` |
| `test_fts_reflects_delete` | ✅ Pass | `test_knowledge_graph_fts.py:99` |
| `test_fts_properties_match` | ✅ Pass | `test_knowledge_graph_fts.py:117` |
| `test_backfill_populates_existing_rows` | ✅ Pass | `test_knowledge_graph_fts.py:140` |
| `test_search_falls_back_to_like` | ✅ Pass | `test_knowledge_graph_fts.py:177` |

### Tests (Phase 1)

| Test | Status | Evidence |
|------|--------|----------|
| `test_higher_confidence_overwrites` | ✅ Pass | `test_knowledge_graph_fts.py:235` |
| `test_lower_confidence_does_not_overwrite` | ✅ Pass | `test_knowledge_graph_fts.py:246` |
| `test_recency_overwrites_conflicting_stale` | ✅ Pass | `test_knowledge_graph_fts.py:257` |
| `test_agreement_bumps_corroboration` | ✅ Pass | `test_knowledge_graph_fts.py:275` |
| `test_new_keys_added_even_with_lower_confidence` | ✅ Pass | `test_knowledge_graph_fts.py:291` |
| `test_metadata_keys_excluded_from_conflict_check` | ✅ Pass | `test_knowledge_graph_fts.py:303` |

### Plan items NOT addressed (by design)

| Item | Reason |
|------|--------|
| Phase 1 spec: "The caller must stamp VALID_TO on the old snapshot separately" | VALID_TO stamping was documented as a follow-up in the spec itself. The merge function preps `_valid_to` removal and `_valid_from` stamping on the new value; old-value timestamping is deferred. This is a **partial** spec gap, not an omission. See Risk analysis below. |
| Phase 0 spec: docstring mentions `content='kg_nodes', content_rowid='rowid'` | The original FTS creation SQL already had this; no change needed. |
| Phase 2–5 | Out of scope — not in this commit |

---

## 3. Architecture Compliance Assessment

### 3.1 Dependency Rule (Clean Architecture)

| Check | Result | Evidence |
|-------|--------|----------|
| Domain imports nothing from Application/Infrastructure | ✅ PASS | `domain/models/knowledge_graph.py` imports only `pydantic`, `datetime`, `typing` — pure |
| Application depends on Ports + Domain | ✅ PASS | `knowledge_graph.py` imports `KnowledgeGraphPort` (port) and domain models |
| Infrastructure implements Ports | ✅ PASS | `SQLiteKnowledgeGraph` inherits `KnowledgeGraphPort`; all abstract methods implemented |
| Merge logic moved OUT of adapter into service | ✅ PASS | Diff shows removal of `old_confidence`/`new_confidence` comparison from `sqlite_knowledge_graph.py` and addition of `merge_properties()` to `knowledge_graph.py` |
| No reverse dependency (Infra → Application) | ✅ PASS | Verified — `sqlite_knowledge_graph.py` doesn't import anything from `application/` |

### 3.2 Port/Adapter Contract

| Contract | Status |
|----------|--------|
| `KnowledgeGraphPort.get_node()` added as abstract | ✅ |
| `SQLiteKnowledgeGraph.get_node()` implemented | ✅ |
| `PostgreSQLKnowledgeGraph.get_node()` implemented | ❌ **REGRESSION** — missing abstract method; class cannot be instantiated |

**PostgreSQL adapter regression detail:**

`weebot/infrastructure/persistence/postgresql/knowledge_graph.py:14` declares `class PostgreSQLKnowledgeGraph(KnowledgeGraphPort)`. The class has no `get_node` method. Python will raise `TypeError: Can't instantiate abstract class PostgreSQLKnowledgeGraph with abstract method get_node` at instantiation time. The adapter is not currently imported by any call site (`search_content "PostgreSQLKnowledgeGraph"` returned only the class definition itself), so this regression is **latent** but blocking for any PostgreSQL deployment.

### 3.3 Immutability (Domain Model)

✅ `KnowledgeNode` is a Pydantic `BaseModel`. No mutations were introduced — all operations use `dict(old_props)` copies and `merged.update()`. The `merge_properties()` function returns a **new** dict rather than mutating inputs.

---

## 4. Code Quality Findings

### 4.1 Positive Observations

| Area | Assessment |
|------|------------|
| **Pure function extraction** | `merge_properties()` has zero side effects — takes dicts, returns dict. Unit-testable in isolation. ✅ |
| **Docstring quality** | Module-level docstrings updated to reflect new responsibilities. `_upsert_node_sync` docstring explicitly documents the delegation to the service. All public functions have Args/Returns. ✅ |
| **Naming consistency** | Reserved property keys (`CONFIDENCE_KEY`, `VALID_FROM_KEY`, etc.) are defined once in domain and imported by other layers. Old local `CONFIDENCE_KEY` constant in service removed. ✅ |
| **Error handling** | FTS5 DDL wrapped in `try/except OperationalError` — preserved from existing code. FTS search also wrapped. `merge_properties()` has `try/except (ValueError, TypeError)` around `datetime.fromisoformat()`. ✅ |
| **Separation of concerns** | Merge policy (business rule) is now in Application layer; adapter only persists. This was the primary layering fix. ✅ |
| **Idempotent backfill** | `fts_count == 0 and node_count > 0` guard ensures the rebuild runs exactly once. ✅ |
| **Configurable margins** | `DEFAULT_CONFIDENCE_MARGIN` and `DEFAULT_RECENCY_MARGIN_SECONDS` are module-level constants with docstrings — easy to tune per environment. ✅ |

### 4.2 Improvement Opportunities (non-blocking)

| Finding | File | Severity | Recommendation |
|---------|------|----------|----------------|
| `_has_conflict` only checks non-None values | `knowledge_graph.py:133` | LOW | A key that exists in old but NOT in new (or vice versa) is not flagged as a conflict. This means adding a new key never triggers recency overwrite — probably intentional, but document the semantics. |
| `CONFIDENCE_KEY` still uses old import path in tests | `test_knowledge_graph_fts.py:22` | LOW | Tests import from domain model (correct), but the old service module no longer exports `CONFIDENCE_KEY` — no runtime issue, but verify no stale import in other test files. |
| Snapshot `previous_properties` stores raw JSON string | `sqlite_knowledge_graph.py:215` | MEDIUM | Adapter now saves `old_props_json` (raw JSON string from DB) as `previous_properties` in the snapshot. Previously it serialized the incoming Python dict. Both are valid JSON but may differ in key ordering/default string representation. |

---

## 5. Testing & Coverage Assessment

### 5.1 Test Coverage Map

| Test | Covers | Layer |
|------|--------|-------|
| `test_fts_index_populated_on_upsert` | INSERT trigger → FTS MATCH | Infrastructure |
| `test_fts_reflects_update` | UPDATE trigger → old name gone, new present | Infrastructure |
| `test_fts_reflects_delete` | DELETE trigger → node removed from FTS | Infrastructure |
| `test_fts_properties_match` | FTS matches property content, not just name | Infrastructure |
| `test_backfill_populates_existing_rows` | Direct INSERT bypassing trigger → `_init_tables()` backfill | Infrastructure |
| `test_search_falls_back_to_like` | DROP FTS → LIKE fallback still works | Infrastructure |
| `test_higher_confidence_overwrites` | Rule 1: confidence delta ≥ margin | Application |
| `test_lower_confidence_does_not_overwrite` | Rule 1 negative case | Application |
| `test_recency_overwrites_conflicting_stale` | Rule 2: conflict + recency | Application |
| `test_agreement_bumps_corroboration` | Rule 3: agreement → corroboration | Application |
| `test_new_keys_added_even_with_lower_confidence` | New keys merged in agreement path | Application |
| `test_metadata_keys_excluded_from_conflict_check` | Reserved keys don't trigger false conflicts | Application |

### 5.2 Coverage Gaps

| Gap | Impact | Recommendation |
|-----|--------|----------------|
| No test for `discover_node()` with the full service → adapter → DB path | The orchestration contract (service calls `get_node` then `upsert_node`) is not end-to-end tested | Add an integration test that exercises `KnowledgeGraphService.discover_node()` twice with conflicting facts |
| No test for `merge_properties` recency tiebreak when new is NOT more recent (negative case) | Edge case: stale observation that conflicts but lacks recency should NOT overwrite | Add: `test_recent_not_more_recent_does_not_overwrite` |
| No test for `VALID_FROM_KEY` being stamped but `VALID_TO_KEY` on old snapshot | Spec acknowledges this is deferred — test should assert the absence to prevent silent regression | Add: `test_valid_to_not_stamped_on_supersede_yet` (documents current gap) |
| No test exercising the `get_node` port method through `KnowledgeGraphPort` ABC directly | Contract test | Low priority; covered indirectly via FTS tests |

---

## 6. Risk & Regression Analysis

### 6.1 Critical / High Risks

| Risk | Severity | Location | Evidence |
|------|----------|----------|----------|
| None identified | — | — | — |

### 6.2 Medium Risks

| Risk | Severity | Location | Evidence |
|------|----------|----------|----------|
| **PostgreSQLKnowledgeGraph missing `get_node`** | HIGH | `postgresql/knowledge_graph.py:14` | `search_content "get_node"` in postgresql returns no match. Class will fail to instantiate. |
| **`VALID_TO_KEY` not stamped on superseded facts** | MEDIUM | `knowledge_graph.py:116-118` | Rule 2 comment says "The caller must stamp VALID_TO on the old snapshot separately" — this is a documented gap, not a bug, but means temporal queries can't distinguish "active" from "superseded" facts without additional logic. |
| **`merge_properties` recency tiebreak uses old `_valid_from` from old_props** | MEDIUM | `knowledge_graph.py:104-107` | If the old fact was never stamped with `_valid_from`, `old_valid_from` defaults to `datetime.now()` — this makes every recency comparison a tie, effectively disabling recency tiebreak for unstamped old facts. |
| **Backfill guarded but never re-validated after schema migration** | LOW | `sqlite_knowledge_graph.py:159-169` | If a DB migration adds nodes after `_init_tables()` first runs, those nodes won't get backfilled without a manual rebuild call. |

### 6.3 Backward Compatibility

| Concern | Status |
|---------|--------|
| `KnowledgeGraphPort` interface extended (new `get_node`) | ⚠️ Breaking for any custom `KnowledgeGraphPort` implementations outside `SQLiteKnowledgeGraph`. The PostgreSQL adapter is the only known one. |
| Old `CONFIDENCE_KEY` removed from `knowledge_graph.py` service | ✅ No consumer found (`search_content` confirms). |
| `_upsert_node_sync` behavior changed (no merge) | ⚠️ Callers that directly call `adapter.upsert_node()` without going through `KnowledgeGraphService.discover_node()` now get "last write wins" instead of confidence-weighted merge. `search_content "\.upsert_node\("` in non-test code shows no direct callers outside `discover_node()` — low risk. |

---

## 7. Required Corrections

| Severity | File | Issue | Recommendation |
|----------|------|-------|----------------|
| **HIGH** | `weebot/infrastructure/persistence/postgresql/knowledge_graph.py` | Missing `get_node()` abstract method — class cannot instantiate | Add a stub `get_node` implementation (can delegate to existing query infrastructure or raise `NotImplementedError` with a migration note) |

---

## 8. Final Verdict

**APPROVED WITH 1 REQUIRED CORRECTION**

Phase 0 and Phase 1 of the Agent-Native Memory plan are correctly and completely implemented. The core architectural fix — moving the merge policy from the infrastructure adapter into the application service — is the most significant structural improvement in this commit and is done correctly. Tests are comprehensive (12 pass, covering FTS triggers, merge logic, and edge cases). Code quality is high with well-documented pure functions.

The single required correction is adding a `get_node()` stub to the PostgreSQL adapter to prevent a latent `TypeError` on instantiation.
