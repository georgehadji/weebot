# P2 Audit Report — Memory Salience + Eviction

**Plan:** `weebot_unified_implementation_plan.md` · P2 Grows-with-you — Memory salience scoring + eviction  
**Date:** 2026-06-22 (implementation + audit)  
**Auditor:** Reasonix Code (automated review + manual verification)  
**Final Verdict:** 🟢 **APPROVED** — 3 blocking + 1 should-fix bugs resolved in audit, 15 tests pass

---

## 1. Executive Summary

The memory salience system is correctly architected — `SalienceScorer` computes salience as `0.4*recency + 0.6*frequency`, `memory_metadata` stores per-entry scores, `PersistentMemoryTool` tracks on read/add, and `MemoryLifecycleService.sweep()` evicts COLD entries past TTL.

**4 audit findings fixed:**
1. 🔴 `_salience_repo` was never initialized → lazy-init now triggers on first call
2. 🔴 `classify()` rule 2 shadowed `hot_min_access` → removed, HOT now requires BOTH recency AND frequency
3. 🟡 `sweep()` duplicated retention logic → now reuses `should_retain()`
4. 🟡 Naive `created_at` entries silently skipped → now normalized to aware datetime

**15 tests pass**, scoring and sweep all verified.

---

## 2. Plan Compliance

| Plan Item | Status | Evidence |
|-----------|--------|----------|
| Memory salience scoring | ✅ Complete | `salience_scorer.py` — `compute_salience()` with recency+frequency |
| memory_metadata storage | ✅ Complete | SQLite table + CRUD in `sqlite_state_repo.py` |
| Wire into PersistentMemoryTool | ✅ Complete (fixed) | `_track_salience()` with lazy-init repo on add/read |
| Wire into MemoryLifecycleService | ✅ Complete | `sweep(repo)` method + 1hr cron job |
| Cron registration | ✅ Complete | `memory_salience_sweep` in `jobs.yaml` + `_capabilities.py` |
| Unit tests | ✅ Complete | `test_salience.py` — 15 tests |

---

## 3. Architecture

| Check | Status |
|-------|--------|
| Pure application-layer scorer | ✅ `salience_scorer.py` — zero infra imports |
| Portal pattern on repo | ✅ `sweep()` takes duck-typed repo |
| Cron follows existing pattern | ✅ Matches `opportunity_scan`, `commitment_heartbeat` |

---

## 4. Code Quality — Audit Fixes

| Finding | Severity | Fix |
|---------|----------|-----|
| `_salience_repo` never initialized → tracking dead | 🔴 | Lazy-init via `hasattr` check on first `_track_salience()` call |
| `classify()` rule 2 shadowed `hot_min_access` | 🔴 | Removed rule 2; HOT now requires `age < hot_ttl AND access >= hot_min_access` |
| `sweep()` duplicated retention logic | 🟡 | Now uses `classify()` + `should_retain()` for eviction decision |
| Naive datetime silently skipped in sweep | 🟡 | Normalised with `.replace(tzinfo=timezone.utc)` before comparison |

---

## 5. Testing

| Suite | Tests | Status |
|-------|-------|--------|
| `test_salience.py` | 15 | 15 passed |
| `test_governed_skill_loop.py` | 14 | 14 passed |
| `test_commitment.py` | 20 | 20 passed |

## 6. Final Verdict

### 🟢 APPROVED

4 bugs fixed in audit. Salience scoring, persistence, tool tracking, lifecycle sweep, and cron wiring all functional. 49 tests pass.
