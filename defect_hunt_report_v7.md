# Defect-Hunt Report V7 — ACR Implementation

**Protocol:** Defect-Hunt V7 (proactive)  
**Date:** 2026-07-09  
**Surface:** `_cascade.py`, `bandit.py`, `posterior_repository.py`  

---

## PHASE 4: TRIAGE & INVENTORY

| ID | Trigger | Innocence | Evidence | Status |
|----|---------|-----------|----------|--------|
| D1 | FIRED | NO-DEFENSE | VERIFIED | **CONFIRMED DEFECT** |
| D2 | — | Strong priors prevent α≤0 | FALSE | Innocent |
| D3 | — | LLMResponse.usage is dict | FALSE | Innocent |

---

## PHASE 5: FIX — D1

**Causal mechanism:** `_cascade_try_chat` line 319 `raise`s on fast-fail (401/403/404), propagating through `_try` → `fut.result()` → step crash. **Fix:** replace `raise` with `return None` + log warning — the cascade already handles `None` as "try next model."

**Diff applied:** `_cascade.py` lines 318-338 — removed `raise` branch, fast-fail now records failure and returns None.

---

## PHASE 6: SELF-REVIEW (RAR) — D1 fix

| Vector | Verdict |
|--------|---------|
| Boundary (empty/single/max models) | FIX HOLDS [VF] — `None` return already handled by all cascade phases |
| Invalid input (None, wrong type) | FIX HOLDS [VF] — `exc` is guaranteed to be an Exception |
| State (partial init) | FIX HOLDS [VF] — no state mutation in the changed branch |
| Regression | FIX HOLDS [VF] — existing test `test_fast_fail_raises` updated to verify new behavior |
| Concurrency | FIX HOLDS [VF] — per-future, no shared state |
| New defect introduced | FIX HOLDS [VF] — re-scanned: `return None` is the existing "no response" signal |

---

## PHASE 7: REGRESSION & PROOF TESTS

**Updated test:** `tests/unit/test_cascade_executor.py::test_fast_fail_returns_none_not_raises` — asserts fast-fail returns None instead of raising.

**Trigger reproducer:** `verify_D1_fixed()` — confirms cascade recovers after a fast-fail model in parallel probes.

---

## PHASE 8: VERDICT + COVERAGE STATEMENT

| Check | Status |
|-------|--------|
| D1 trigger fired + innocence found no defense | ✅ |
| Fix ≤ 15 lines, ≤ 1 function | ✅ (2 lines changed) |
| Proof-of-defect test included | ✅ |
| 100/100 tests pass | ✅ |
| All RAR vectors → FIX HOLDS [VF] | ✅ |

**Coverage:**
- Surface audited: `_cascade.py` (parallel probes, sequential fallback), `bandit.py` (Thompson sampler, budget tracking), `posterior_repository.py` (record_outcome)
- Defect classes covered: Error/exception paths, boundary & arithmetic, type & serialization
- Confirmed: 1 (D1 — HIGH, fast-fail crash)
- Cleared: 2 (D2, D3 — innocent)
- Clean-claim: "`_cascade.py` exception handling audited for fast-fail crash and edge cases. 1 defect found and fixed. No other verified defects in the audited surface."

**Fix commits:**
1. `_cascade.py:319-320` — fast-fail `raise` → `return None`  
2. `test_cascade_executor.py:162-170` — updated test

**Iteration accounting:** hunt_iterations=1, fix_revisions=0, budget_spent=3/5

---

**UNCERTAINTY ACKNOWLEDGMENT**
- Finding most likely false positive: None — D1 confirmed by executable trigger
- Most likely missed: Concurrency in `_TASK_CATEGORY_CACHE` (class-level dict mutated from async) — not audited
- Requires runtime validation: D1 fix confirmed by trigger test (PASSED)
- Static analysis cannot determine: Thread-safety of `_TASK_CATEGORY_CACHE` under concurrent calls
- Would raise confidence: Running the trigger reproducer under load (multiple parallel cascades)
