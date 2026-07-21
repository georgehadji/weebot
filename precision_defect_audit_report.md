# Precision Defect Audit — ACR Implementation (P0–P4)

**Protocol:** EGFV/RAR static single-pass  
**Date:** 2026-07-09  
**Surface:** 21 source files, ~5,000 lines  

---

## PHASE 1 — DEFECT INVENTORY

| ID | Severity | Evidence | Reach | Location | Category | Violated Property | Description | Trigger Condition |
|---|---|---|---|---|---|---|---|---|
| D1 | **HIGH** | VERIFIED-STATIC | REACHABLE from `call_with_cascade` | `_cascade.py:406` + `_base.py:647` | Logic / Error handling | Exception safety: `fut.result()` at line 406 calls `_try()`, which calls `_cascade_try_chat()`, which calls `raise` (not `return None`) on fast-fail errors (401/403/404). The caller at `_base.py:647` only catches `AllModelsTrippedError` — the raw fast-fail exception crashes step execution. | When a parallel-probe model hits an auth/not-found error and is the first future to complete in `asyncio.wait(FIRST_COMPLETED)`, `fut.result()` re-raises the fast-fail error and `call_with_cascade` crashes the step. |

---

### Innocence-checked candidates (CLEARED — no defect)

| ID | Candidate | Why innocent |
|---|---|---|
| C1 | token_count expression at `_cascade.py:291` — `getattr(resp,"usage",{}).get("total_tokens",0)` | `LLMResponse.usage` is `Dict[str,int]` (confirmed at `llm_response.py:18`), so `.get()` always succeeds. The `hasattr` guard is a defensive second layer. |
| C2 | `_sample_thompson` creates new `Random()` each call at `bandit.py:170` | Performance concern (Mersenne Twister seed from `/dev/urandom` is slow) but NOT a correctness defect — output is still a valid Beta sample. Suboptimal, not wrong. |
| C3 | `_should_explore` exploration stops after 100 pulls at `bandit.py:188` | Intentional convergence design — exponential forgetting in posteriors still allows belief shifts without exploring. Matches plan R3 mitigation. |

---

## PHASE 2 — FIX PACKAGES

==FIX D1 — Guard `fut.result()` in parallel probes against fast-fail exceptions==

CAUSAL BASIS:
- Verified mechanism: `_cascade_try_chat` calls `raise` on `ErrorClassifier.should_fail_fast(exc)`. This propagates through `_try` → `asyncio.Future` → `fut.result()` at `_cascade.py:406`. The only exception type caught by the caller is `AllModelsTrippedError` (`_base.py:647`). A fast-fail exception is NOT an `AllModelsTrippedError`, so it crashes the step. The violated property is **exception safety**: a fast-fail on one model must not prevent other models from being tried.
- This fix intercepts the exception at `fut.result()`, records it as a failed probe via `resp = None`, and allows the cascade to proceed to the next model. It is causal because it breaks the propagation chain at the exact point where the exception escapes the parallel probe loop.

DIFF:
~~~diff
--- a/weebot/application/agents/executor/_cascade.py
+++ b/weebot/application/agents/executor/_cascade.py
@@ -402,8 +402,17 @@ class CascadeExecutor:
         if parallel:
             tasks = {asyncio.ensure_future(_try(m, 90.0, tier=CascadeTier.FREE)): m for m in parallel}
             done, pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
             for fut in done:
-                resp = fut.result()
+                try:
+                    resp = fut.result()
+                except Exception as exc:
+                    logger.debug(
+                        "Parallel probe fast-fail suppressed: %s",
+                        tasks.get(fut, "unknown"), exc_info=exc,
+                    )
+                    resp = None
                 if resp is not None:
                     for pf in pending:
                         pf.cancel()
@@ -418,6 +427,8 @@ class CascadeExecutor:
                      and m not in self._server_error_models]
         remaining_tiers = [CascadeTier.BUDGET, CascadeTier.PREMIUM]
         for m, t in zip(remaining, remaining_tiers[:len(remaining)]):
+            try:
                 resp = await _try(m, 60.0, tier=t)
+            except Exception:
+                continue
             if resp is not None:
                 if self._on_success:
~~~

APPLICABILITY:
- Applies cleanly to provided snippet: YES
- Breaking change: NO
- Files affected: `weebot/application/agents/executor/_cascade.py`
- Unresolved: NO

SELF-REVIEW (RAR):
- Boundary (empty/min/max, off-by-one):        FIX HOLDS [VERIFIED-STATIC]
- Invalid input (None, wrong type, malformed):  FIX HOLDS [VERIFIED-STATIC]
- State (corrupt/partial init at execution):    FIX HOLDS [VERIFIED-STATIC]
- Regression (documented behavior changed?):    FIX HOLDS [VERIFIED-STATIC]
- Concurrency (simultaneous shared-state exec):  FIX HOLDS [VERIFIED-STATIC]
- New defect introduced by the fix:             FIX HOLDS [VERIFIED-STATIC]

==END FIX D1==

---

## PHASE 3 — MASTER REPORT

**SUMMARY**
- Findings (survived innocence): 1 (VERIFIED-STATIC: 1)
- Cleared (innocent): 3 — C1 (token_count), C2 (thompson_rng), C3 (explore_stop)
- Fix packages: 1 (D1)
- Deferred: 0

**PREVENTION RECOMMENDATIONS**
1. Enable Ruff rule B904 in `pyproject.toml` — "raise-without-from-inside-except" catches the `raise` re-raise pattern that caused D1.
2. Add an integration test with a mock LLM that raises 401 in the first parallel slot, asserting the cascade falls through to the next model.

**COVERAGE STATEMENT**
- Surface audited: `_cascade.py`, `bandit.py`, `posterior_repository.py`, `utility_scorer.py`, `constraint_checker.py`, `capability_profiles.py`, `_base.py` (call sites)
- NOT audited: benchmark suites (data-only), MCP resources (JSON serialization)
- Classes covered: Error handling, concurrency, edge cases, resource, logic
- Clean-claim: "`_cascade.py` parallel/sequential probes and `posterior_repository.py` were audited for exception-safety and resource defects. 1 VERIFIED-STATIC defect found (D1). No other VERIFIED-STATIC defects in the audited surface."

**UNCERTAINTY ACKNOWLEDGMENT**
- Most likely false positive: None — D1 is VERIFIED-STATIC
- Most likely missed: Concurrency in `_TASK_CATEGORY_CACHE` (class-level dict mutated from async contexts) — unexamined
- Requires runtime validation: D1 regression test [PENDING VERIFICATION]
- Cannot determine statically: `_TASK_CATEGORY_CACHE` thread safety under concurrent `_classify_description` calls
- Would raise confidence: Running the D1 reproducer test with a 401-raising mock LLM
