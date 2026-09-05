# Defect Hunt — Wave 0 Baseline & Instrument Repair

**Executed:** 2026-09-05
**Plan:** [`tasks/specs/defect_hunt_v7_execution_plan.md`](../specs/defect_hunt_v7_execution_plan.md) — Wave 0
**Protocol:** V7 (proactive). Wave 0 is a *precondition*, not a hunt: it repairs the
detectors so that waves W1–W8 inherit trustworthy signal.
**Baseline commit:** `df40fb1` (branch `claude/weebot-codebase-analysis-gwg92i`)

---

## Why this wave exists

The V7 activation contract states that flagging correct code as defective is a defect of the
protocol, treated as severely as missing a real bug. A hunt inherits the reliability of its
detectors. Measurement found that **seven of this repo's gates were unreliable**, in three
recurring shapes:

| Shape | Instances |
|---|---|
| A gate that reports clean while checking nothing | I1 |
| A gate that reports noise (duplicates + false positives) | I3, I8a, I8b |
| A gate that can never pass, so nobody runs it | I7 (three targets) |
| A gate green only because nothing runs it in that combination | B2 |

All three shapes produce the same outcome: the gate stops carrying information.

---

## Instrument findings and repairs

### I1 — `lint-bare-except-pass` reported clean over 139 real sites

The Makefile regex required `pass` on the **same line** as `except`, so the ordinary form

```python
except Exception:
    pass
```

could never match. `make lint-bare-except-pass` exited 0 while an AST scan found **139**
handlers whose entire body is `pass`.

**Repair:** new `scripts/lint_except_pass.py` — AST-based (`ast.ExceptHandler` whose body is
exactly `[ast.Pass]`, plus the `...` variant), wired into the Makefile target.
**Ratchet:** `CEILING = 139`, blocking above it.
**Proof it blocks:** adding one new silent handler → `140 > 139`, exit 1. Removing it → exit 0.

### I2 — `pyproject.toml` cited rule codes that do not mean what it claimed

- The comment on ruff's `"B"` selector claimed it "includes B110 try-except-pass". **Ruff has no
  `B110`** — it is a *bandit* code. Ruff's equivalent is `S110` (flake8-bandit), and `S` is not
  in the `select` list.
- The per-file-ignore comment described `B011` as "bare except: pass without logging". Ruff's
  `B011` is **`assert-false`**.

**Repair:** both comments corrected to describe the actual enforcement path
(`scripts/lint_except_pass.py` blocking; `bandit` advisory in CI). `S110` was deliberately *not*
added to `select` — it would duplicate the new AST gate without adding coverage.

### I3 — `lint_async_io.py` reported 83 violations for 29 real sites

Three separate defects, all inflating the count:

1. **Scope.** `ast.walk` from an `AsyncFunctionDef` descends into nested `def`s, so the correct
   `to_thread` pattern was reported as a violation. `strategy_store.py`, `skill_variant_store.py`
   and `sqlite_summary_repo.py` were flagged for `sqlite3.connect` inside a nested sync helper
   that is immediately offloaded via `return await asyncio.to_thread(_insert)` — **textbook
   correct code, reported as broken.**
2. **False positive.** `\bopen\s*\(` matches after a dot, so `aiofiles.open(...)` — async-native —
   was flagged as blocking.
3. **Duplicates.** One report per `Call` node rather than per line, so
   `json.loads(p.read_text(...))` counted twice.

Plus `SKIP_PATHS` was a substring test against the whole path, so any path merely *containing*
`scripts`/`Output`/`examples` was skipped.

**Repair:** scope-aware `_own_body()` walker that does not enter nested function scopes; an
`ASYNC_SAFE_PREFIXES` allowlist; per-line deduplication; `SKIP_PATHS` matched against path
components.

| | Before | After |
|---|---|---|
| Reports | 83 | **29** |
| Unique sites | 53 | **29** |
| Reports per site | 1.57 | **1.00** |

The 29 remaining are genuine and are W3/W7 material.

### I4 — the architecture gate errored instead of checking

`test_core_no_application_imports` shelled out to a bare `["lint-imports", ...]`. Under
`.venv/bin/python -m pytest` the venv's `bin/` is not on `PATH`, so it raised
`FileNotFoundError` — a red test that said nothing about the architecture.

**Worth stating plainly: this was never an architecture violation.** `lint-imports` itself
reports the `core-no-app` contract **KEPT**. The test could not run; it did not disagree.

**Repair:** resolve the console script next to `sys.executable` first, fall back to
`shutil.which`, and skip with an explicit reason if genuinely absent. CI installs import-linter,
so the skip cannot mask a regression there, and `make lint-imports` remains the enforcing path.

### I5 — documented coverage floor did not match the enforced one

`AGENTS.md` stated CI enforces **≥ 60%**. The workflow and `.coveragerc` both enforce **52%**.
**Repair:** `AGENTS.md` corrected to 52% in both the prose and the example command.

### I6 — the exemption inventory was 15 entries out of date

`.importlinter` carries **67** `ignore_imports` entries across 6 contracts;
`tasks/plans/ignore_imports_taxonomy.md` documented **52** across 4.

A ratchet already exists and is enforced —
`tests/unit/test_architecture_fitness.py::test_ignore_imports_under_target` asserts `≤ 72`. This
is the repo's own precedent for the ratchet pattern used throughout this wave.

**Repair:** taxonomy header re-inventoried with the true per-contract breakdown, the enforced
ceiling recorded, and a note that the per-contract tables below it still describe the original 52
and are a partial map rather than a census.

### I7 — `make check` was red on a clean checkout, and three of its gates were not in CI

`make check` had **three** permanently-failing prerequisites. A gate that can never pass is a
gate nobody runs.

| Target | Was | Now |
|---|---|---|
| `lint-async-io` | exit 1 (83 reports); **absent from CI** | ratcheted at 29; **added to CI** |
| `lint-no-print` | exit 1 (153 matches) | ratcheted at 143 |
| `lint-env-access` | exit 1 (95 matches); non-blocking in CI | ratcheted at 73 |

**Repair:** all three ratcheted; `lint_except_pass.py` and `lint_async_io.py` added to the
`lint-and-arch` CI job as blocking steps.

### I8 — `--exclude-dir` was inert in two targets *(found during I7)*

GNU grep matches `--exclude-dir` against a directory's **base name**. Both
`--exclude-dir=weebot/GitNexus-main` (in `lint-no-print`) and `--exclude-dir=weebot/config` (in
`lint-env-access`) contain a `/` and therefore excluded nothing.

Consequences, both now corrected:

- `lint-no-print` scanned vendored `weebot/GitNexus-main/` — 10 of its 153 matches.
- `lint-env-access` scanned `weebot/config/` itself, **the one module permitted to read the
  environment** — 22 of its 95 matches were false positives. The real count is 73, not the 95/96
  the CI comment records.

---

## Baseline defect repaired

### B1 — a proof test for a production hang had gone inert

`tests/unit/test_latex_document.py::test_compile_timeout_returns_result_instead_of_hanging`
failed on `main` and on every PR against it.

The font validation added by `0440f3a` (findings E/F) returns at `latex_compiler.py:161` before
`compile()` ever reaches the `subprocess.Popen` at `:173`. The test exists to guard the
orphaned-grandchild hang fixed by `9cd2d1d` (finding G), and asserts on
`CompileErrorCategory.TIMEOUT` — a category it could no longer reach:

```
elapsed=0.01  ok=False
ERROR category=CompileErrorCategory.UNKNOWN
      msg='Required font(s) not installed: GFS Didot, GFS Neohellenic'
```

This is a **fix interaction**: one work item's fix silently disabled another's regression guard.
Exactly the failure mode V7's Phase 5 fix-interaction check exists to prevent, and the reason
W8 (seams) is in the plan.

**Repair:** the test neutralises the font precondition it is not testing. The production font
check is correct and unchanged — a missing font otherwise yields a silent `nullfont` PDF, which
is why `0440f3a` added it.


### B2 — Alembic's logging config silenced every logger, failing 11 tests

Found while validating this wave: `pytest tests/unit/` was green (3597 passed) but
`pytest tests/` — the repo's own `make test` — was **red with 11 failures**. Same tests, different
result depending on what else ran. All 11 assert on log output.

**Attribution, proven not assumed.** The full suite was run on the clean baseline `df40fb1` with
this wave's changes stashed: **13 failed**. With them applied: **11 failed**. The difference is
exactly the two this wave fixes (I4, B1). The other 11 are pre-existing and untouched by it.

**Root cause, bisected.** `tests/integration` alone reproduces it; within it, the single file is
`test_migration_schema_matches_app.py`, which runs Alembic in-process. `alembic/env.py:18` calls
`fileConfig(config.config_file_name)`, and `logging.config.fileConfig` defaults to
`disable_existing_loggers=True`. `alembic.ini` carries `[loggers]`/`[handlers]`/`[formatters]`,
so the call takes effect and **disables every logger already created in the process** for the
remainder of the run. Every later `caplog` assertion then sees nothing.

```
secret-accessor redaction tests alone            -> 5 passed
after tests/integration                          -> 4 failed
after the polluting file alone                   -> 4 failed
after `disable_existing_loggers=False`           -> 9 passed
```

**Fix:** `fileConfig(config.config_file_name, disable_existing_loggers=False)` — one line, one
call site, causal rather than symptomatic. It does not touch the 11 tests; it removes the
mechanism that broke them. Harmless for a standalone `alembic` invocation, and correct for the
in-process use (migration tests, programmatic upgrades) that this env.py also serves.

**Why CI never caught it:** no CI job runs the whole `tests/` tree. The workflow runs
`tests/unit/` and several targeted files in separate jobs, each of which passes in isolation.
The failure only appears when unit and integration tests share a process — which is exactly what
`make test` does and what no CI job does.

**This is the only production file this wave touches**, and it is included because leaving it
would have meant reporting `make check` as repaired while it was still red.

---

## Exit criteria

| Criterion | Status |
|---|---|
| `pytest tests/unit/` green | ✅ 3597 passed, 0 failed (was 3595 passed / **2 failed**) |
| `pytest tests/` (full suite) green | ✅ 3679 passed, 0 failed (was 3666 passed / **13 failed**) |
| **`make check` green** | ✅ `=== All checks passed ===` — it was red on a clean checkout |
| `lint-imports` 7 kept / 0 broken | ✅ |
| `ruff check --select F821,E9` clean | ✅ |
| Every gate passes or is ratcheted with a recorded number | ✅ |
| Every ratchet proven to block a regression | ✅ (probe added → exit 1; removed → exit 0) |

### Recorded ceilings

| Gate | Ceiling | Where |
|---|---|---|
| Silent except handlers | **139** | `scripts/lint_except_pass.py` |
| Blocking I/O in async | **29** | `scripts/lint_async_io.py` |
| `print()` in production | **143** | `Makefile` (`PRINT_CEILING`) |
| Bare env reads | **73** | `Makefile` (`ENV_ACCESS_CEILING`) |
| `ignore_imports` | **72** | `test_architecture_fitness.py` (pre-existing) |

**A ceiling may be lowered; it must never be raised.** §11 of the plan names the standing risk:
a ratchet that never moves is a fail-open gate with extra steps. W7 is where the 139 and the 29
get paid down.

---

## What this wave deliberately did not do

- **Almost no production code was changed.** `alembic/env.py` is the single exception (B2, one
  argument), included because without it `make check` stays red and I7 would be unrepaired.
  Every other change is to a test, a linter, a Makefile target, a CI step, or documentation.
  B1 was repaired in its test, because the production behaviour there was correct.
- **No new lint rules were added.** `S110` was considered and rejected as duplicative. Expanding
  `lint_async_io.py`'s pattern set (it misses `requests`, `httpx`, `socket`, `shutil`) is W3/W7
  work, not instrument repair — adding patterns changes what is measured, and Wave 0's job is to
  make the existing measurement honest.
- **No debt was paid down.** 139 silent handlers, 29 blocking calls, 143 prints and 73 bare env
  reads all remain. They are now *counted correctly and held from growing*, which is the
  precondition for paying them down, not the payment.

---

## Next

Wave 1 — security & trust boundary (T1, T2 · classes C1, C2, C3). Entry material is §7.3 D1–D12
of the plan, plus seed **S1** (`output_path("/etc/passwd")` returns `/etc/passwd`), which is
already verified and awaiting its Phase 3 reachability analysis.
