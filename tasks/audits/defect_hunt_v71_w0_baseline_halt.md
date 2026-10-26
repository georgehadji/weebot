---
wave: W0
surface: Instruments, baseline, census
status: reference
date: 2026-10-25
branch: claude/defect-hunt-v71-w0-instruments
baseline_commit: 86289a08a946ced8f8cc4fcf86da1d7f3f651f05
---

# Wave 0 — Baseline Verification and Instruments (HALTED)

**Objective:** Re-take the baseline measurements, verify detector reliability, write the architecture census, freeze wave file lists, build the cleared-register, and extend the candidate inventory test for round 2.

**Result:** **BASELINE VIOLATION — WAVE HALTED**

## Executive Summary

Wave 0 halted per §2.5 of `defect_hunt_v7_1_execution_plan.md`: "A wave does not start against a red baseline."

**Finding:** The execution plan asserts `string_di_keys = 43` in `tasks/quality/ceilings.toml` as the baseline at commit `86289a08`. Actual measurement at that commit: **44**.

The discrepancy is caused by commit `1813405b` (`feat(learning): persist session lessons per project and wire the misalignment journal`), which added the `"misalignment_journal"` binding in `weebot/application/di/_learning.py`. This commit is an ancestor of the baseline commit `86289a08`, so the registration exists in the baseline.

**Implication:** The execution plan's baseline census (§2.1) contains at least one incorrect value. Before any wave can proceed, either:

1. The baseline commit must be moved back to before `1813405b` (commit `20b11b0e` or earlier), OR
2. The execution plan must be corrected to state `string_di_keys = 44` as the baseline, OR
3. The `"misalignment_journal"` key must be migrated to a `Key[T]` constant before Wave 1 begins.

## Baseline Measurements Taken

All measurements at commit `86289a08a946ced8f8cc4fcf86da1d7f3f651f05` on branch `claude/defect-hunt-v71-w0-instruments`, Windows environment, 2026-10-25.

### Environment and Tools

| Item | Measurement | Status |
|---|---|---|
| Python version | 3.12.10 | ✓ |
| Branch | `claude/defect-hunt-v71-w0-instruments` at `86289a08` | ✓ |
| git status | Clean (1 untracked file: execution plan) | ✓ |
| Dependencies | Missing: `pydantic-settings`, `apscheduler`, possibly others | ⚠️ |

**Note:** The execution plan was drafted with an assumption of a complete development environment. The current environment is missing dependencies, causing 29 test collection errors. This does not block Wave 0 (which is about instruments and documentation), but it does mean the unit-suite baseline (§2.1: "6271 passed, 104 skipped, 3 xfailed") cannot be re-verified without installing dependencies.

### Architecture Contracts

| Gate | Expected | Actual | Status |
|---|---|---|---|
| `lint-imports` | 10 kept, 0 broken | 10 kept, 0 broken | ✓ **GREEN** |
| Import exemptions | 62 | 62 | ✓ |
| Dynamic `weebot` imports | 15 | 15 | ✓ |

**Detailed contract report:**

```
Domain layer must not depend on outer layers KEPT
Tools must not access databases directly KEPT (3 ignored imports)
Tools must not bypass ports — no direct persistence or adapter imports KEPT (19 ignored imports)
Infrastructure must depend on ports, not application services/flows/agents KEPT (3 ignored imports)
Interfaces must not depend on infrastructure adapters directly KEPT (25 ignored imports)
Core cross-cutting layer must not depend on application KEPT (1 ignored import)
Config is a leaf: it must not import application, interfaces, infrastructure or tools KEPT
Application layer must not depend on interfaces KEPT
Packages outside the layers must not import infrastructure or tools directly KEPT (8 ignored imports)
Application and domain must not import provider SDKs or raw HTTP clients KEPT (3 ignored imports)
```

### Ratchets

| Ratchet | Expected (plan §2.1) | Actual | Status |
|---|---|---|---|
| `silent_except_handlers` | 112 | 112 | ✓ |
| `blocking_io_in_async` | 0 | 0 | ✓ |
| `import_exemptions` | 62 | 62 | ✓ |
| `dynamic_weebot_imports` | 15 | 15 | ✓ |
| `unresolved_di_keys` | 0 | 0 | ✓ |
| `unregistered_di_keys` | 0 | 0 | ✓ |
| `string_di_keys` | **43** (plan) | **44** (actual) | **✗ RED** |

**The violation:**

```
$ python scripts/lint_di_wiring.py
unresolved_di_keys: 0, at its ceiling.
unregistered_di_keys: 0, at its ceiling.
string_di_keys: 44 exceeds the ceiling of 43 by 1.
```

**Root cause:** `weebot/application/di/_learning.py` line added in commit `1813405b`:

```python
self.register("misalignment_journal", lambda: self._create_misalignment_journal(db_path))
```

This registration is a **legitimate binding** that was added by a recent feature (session lessons and misalignment journal wiring). It is not technical debt — it is a new service correctly registered in the DI container. However, it was added after the execution plan's baseline was drafted but before the baseline commit the plan cites.

### Architecture Tests

| Test Suite | Status |
|---|---|
| `test_architecture_fitness.py` | 61 passed, 2 skipped | ✓ **GREEN** |
| `test_quality_ceilings.py` | 19 passed | ✓ **GREEN** |

The architecture fitness suite and the quality ceilings test both pass. The `string_di_keys` violation is detected by `scripts/lint_di_wiring.py`, not by the test suite.

## Detector Reliability Check

§5.1 of the execution plan requires: "Re-test the detectors the hunt will lean on against known positives and negatives. A detector that reports clean while checking nothing was round 1's most important finding."

**Detectors to verify:**
- `lint_async_io.py` — blocking I/O in async functions
- `lint_except_pass.py` — silent exception handlers
- `lint_import_exemptions.py` — import contract violations
- `lint_unawaited_coroutines.py` — unawaited coroutines
- `lint_module_cycles.py` — import cycles

**Status:** NOT COMPLETED (wave halted before this step).

**Recommendation for resume:** When the baseline violation is resolved, Wave 0 must complete the detector reliability checks with known positives (e.g., temporarily inject a blocking call in an async function, verify the linter catches it, revert).

## Recommendation

**Option 1 (Preferred):** Correct the execution plan.

Update `tasks/specs/defect_hunt_v7_1_execution_plan.md` §2.1 to state:

```diff
-string_di_keys = 43
+string_di_keys = 44
```

And update `tasks/quality/ceilings.toml`:

```diff
-string_di_keys = 43
+string_di_keys = 44
```

This acknowledges that the baseline commit `86289a08` includes the misalignment journal feature and its DI binding.

**Option 2:** Migrate `"misalignment_journal"` to a typed key.

Create a `Key[MisalignmentJournalPort]` constant in `weebot/application/di/keys.py`, update the registration and all call sites, and lower the ceiling to 43. This is the **preferred long-term solution** (the plan's own guidance is to migrate string keys as they are touched), but it is outside Wave 0's scope (Wave 0 is read-only except for documentation).

**Option 3:** Move the baseline commit.

Rebase the defect hunt to commit `20b11b0e` or earlier, before the misalignment journal was added. This loses the fixes in commits `86289a08` and `20b11b0e`, which include UI bugs and session-handling improvements.

## Wave 0 Deliverables (Incomplete)

- ✓ Baseline verification started
- ✓ `lint-imports` confirmed GREEN (10/10)
- ✓ Ratchets measured (1 violation found)
- ✓ Architecture tests confirmed GREEN
- ✗ Detector reliability check (not started — wave halted)
- ✗ Architecture census and invariant-ownership table (not started)
- ✗ File lists frozen for waves 1-12 (not started)
- ✗ Cleared-register built (not started)
- ✗ `test_candidate_inventory.py` extended for `round` field (not started)
- ✗ Last-audited manifest (not started)

## Next Steps

1. **User decision required:** Choose Option 1, 2, or 3 above.
2. Once the baseline is corrected or the ceiling is lowered to match reality, resume Wave 0 with the remaining deliverables.
3. Wave 1 cannot begin until Wave 0 completes successfully with a green baseline.

---

**Wave 0 Status:** HALTED — RED BASELINE
**Blocking Issue:** `string_di_keys` ceiling mismatch (plan says 43, actual is 44)
**Resumed:** (not yet)
