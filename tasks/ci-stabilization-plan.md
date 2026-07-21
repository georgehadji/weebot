# CI Stabilization & Architecture-Debt Remediation Plan

> **Goal:** turn the repository's CI from fully red to green, fixing every
> pre-existing failure **without weakening the Clean/Hexagonal architecture**
> — respecting the dependency rule (`Interfaces → Infrastructure → Application →
> Domain`), the `.importlinter` contracts, and the architecture-fitness gates.
>
> **Status of the scientific-book feature (PR #46):** the new `document/`
> pipeline is **clean** — `weebot/domain/models/book.py` is domain-pure
> (imports only stdlib + pydantic), the application/infrastructure modules add
> **zero** new `import-linter` violations, and its 12 tests pass. None of the
> failures below are caused by this branch; they all fail on `main` too. This
> plan is therefore a **separate concern** from the book feature (see §7,
> *PR strategy*).

---

## 1. How this was verified (method)

CI runs on **Python 3.12**. The local interactive shell defaults to Python
3.11, where `numpy==2.5.1` (requires-python ≥3.12) cannot install — so a naive
local `pytest` misleads with spurious `ModuleNotFoundError`s. The real CI
environment was reproduced faithfully:

```bash
python3.12 -m venv /tmp/ci-venv
/tmp/ci-venv/bin/pip install -r requirements.txt      # resolves cleanly on 3.12
```

Every job in `.github/workflows/architecture.yml` was then run with its exact
command. `pydantic-settings` and `pillow` — absent from `requirements.txt` —
are pulled transitively (`mcp==1.28.1 → pydantic-settings`, `matplotlib →
pillow`), so they are **present on CI**; the local 3.11 "missing dependency"
was an artifact of the partial env, **not** a CI bug. (They are still worth
pinning — see E3.)

---

## 2. Failure inventory (observed, reproduced)

CI has **6 jobs**; 5 fail, 1 is skipped behind a failed gate.

| CI job | Command | Result | Root-cause group |
|---|---|---|---|
| Architecture Fitness | `make lint-imports` + `pytest tests/unit/test_architecture_fitness.py` + `make check-arch` | **FAIL** | D (debt), plus `lint-imports` exit 1 |
| Unit Tests | `pytest tests/unit/ -x --cov-fail-under=48` | **FAIL** | A, B, C, D |
| Persistence | `pytest tests/e2e/test_persistence.py` | **FAIL** (5/5) | A1 |
| CQRS Integration | `pytest tests/integration/test_cqrs_handlers.py` | **FAIL** (5 errors) | A2 |
| E2E / Perf / Chaos | `pytest tests/e2e/ -m "not external"` | **FAIL** (7) | A1, A2 |
| Docker Build Smoke | build + health | **SKIPPED** (`needs: architecture-fitness`) | unblocked by D |

### Failing tests grouped by root cause

- **A1 — `sqlite3.Row.get()` misuse** (`weebot/infrastructure/persistence/sqlite_state_repo.py:345,352`).
  `_row_to_session` calls `row.get("context_json")` / `row.get("title", "")`,
  but rows are `sqlite3.Row`, which has **no `.get()`**.
  Breaks: `test_persistence.py` (5), `test_flow_e2e.py::TestConcurrentFlows`,
  `test_flow_e2e.py::TestChaosRecovery`.
- **A2 — `InMemoryStateRepository` violates its port.**
  `weebot/infrastructure/persistence/in_memory_state_repo.py` does not
  implement 4 abstract methods declared on the state/checkpoint port
  (`save_checkpoint`, `load_checkpoint`, `delete_checkpoint`,
  `list_checkpointed_sessions`) → `TypeError: Can't instantiate abstract
  class`. Breaks: `test_cqrs_handlers.py` (5), `test_cqrs_persistence.py` (5),
  `test_planning.py` (2).
- **A3 — `list_sessions` dropped the `load_events=False` fast path.**
  `sqlite_state_repo.py:293` calls `self._row_to_session(r)` (defaults
  `load_events=True`), so listing sessions needlessly deserializes every
  session's events. The audit test
  `test_audit_findings.py::TestLoadEventsParameter::test_list_sessions_uses_load_events_false`
  guards exactly this and now fails.
- **B1 — Model catalog / cascade drift.**
  `test_catalog_validator.py::test_default_catalog_is_clean` reports 5 role→model
  references with no catalog entry: `meituan/longcat-2.0` (coder),
  `moonshotai/kimi-k3` (coder), `thinkingmachines/inkling` (reviewer, vision),
  `meta/muse-spark-1.1` (admin).
- **C1 — Test-isolation pollution.**
  `test_secret_accessor.py` (4 redaction tests) **pass in isolation** (19/19)
  but **fail inside the full `tests/unit/` run** → global-state pollution
  (logging config or the `SecretAccessor` singleton) from an earlier test.
- **D — Architecture-fitness debt** (all in `tests/unit/test_architecture_fitness.py`):
  - **D1** `test_no_flat_files_at_root`: committed artifact dir
    `weebot/Output/thessaloniki-constructions/` (a generated website) sits at
    the package root.
  - **D2** `test_no_settings_import_in_tools`: `weebot/tools/berb.py`,
    `reasoner.py`, `scraper.py` import `WeebotSettings` at module level instead
    of using `ToolConfig` constructor injection.
  - **D3** `test_god_modules_under_800_lines`:
    `weebot/application/services/model_registry/_catalog.py` = **3792 lines**
    (limit 3200).
  - **D4** `test_core_no_application_imports` == `make lint-imports`:
    **3 of 6 contracts broken**:
    1. *Tools must not access databases directly* — `checkpoint_store → sqlite3`.
    2. *Tools must not bypass ports* — `tools.base → application.models.tool_collection → application.services.metrics_bridge → infrastructure.observability.metrics`.
    3. *Interfaces must not depend on infrastructure* — `interfaces.factories → application.models.plan_act_flow_config → …tool_collection → …metrics_bridge → infrastructure.observability.metrics`.
  - **D5** `test_ignore_imports_under_target`: `.importlinter` has **60**
    `ignore_imports` (target ≤ 44).

> **Ownership check:** `git diff --name-only origin/main..HEAD` touches none of
> the files above. Every failure is pre-existing tech debt on `main`.

---

## 3. Guiding principles for the fixes

1. **Fix causes at the correct layer.** Persistence bugs are fixed in
   `infrastructure/persistence`; port conformance is enforced against the
   Application-layer port; catalog drift is a config/data fix in the
   Application service — never by loosening a Domain rule.
2. **Test doubles are first-class port implementations.** A2 is fixed by making
   the in-memory double *satisfy* the port, never by narrowing the port.
3. **No new `ignore_imports`.** D4/D5 are fixed by *removing* real violations,
   not by whitelisting them. Any unavoidable exception needs an ADR.
4. **Prove each fix.** Every group ends by re-running the exact CI command for
   the job(s) it unblocks in the Python 3.12 venv.
5. **Coverage stays ≥ 48%** (the `--cov-fail-under=48` gate on Unit Tests).

---

## 4. Remediation, by group

### Group A — Persistence correctness & port conformance  *(Infrastructure)*
Unblocks **Persistence**, **CQRS Integration**, most of **E2E**, and the A/B
slice of **Unit Tests**. Highest ROI; do first.

- **A1 — `sqlite3.Row` has no `.get()`.**
  Root fix: make rows behave like mappings at the boundary. Preferred:
  set `conn.row_factory = sqlite3.Row` **and** replace `.get()` access in
  `_row_to_session` with a small helper (`_col(row, name, default)`) that does
  `row[name] if name in row.keys() else default`, or convert once via
  `d = dict(row)` and read from `d`. Apply to lines 345 (`context_json`) and
  352 (`title`). Audit the whole file for other `row.get(` uses.
  *Verify:* `pytest tests/e2e/test_persistence.py` and the two
  `test_flow_e2e.py` cases (`TestConcurrentFlows`, `TestChaosRecovery`).

- **A2 — Complete `InMemoryStateRepository`.**
  Implement the 4 checkpoint methods on
  `weebot/infrastructure/persistence/in_memory_state_repo.py` against the
  contract in `weebot/application/ports/checkpoint_port.py` /
  `state_repo_port.py` (dict-backed, same semantics as
  `SQLiteCheckpointStore`: save/replace by session id, load-or-None,
  delete idempotent, list ids). Keep it dependency-free (no sqlite) so it
  stays a pure in-memory double.
  *Verify:* `pytest tests/integration/test_cqrs_handlers.py`,
  `tests/unit/test_cqrs_persistence.py`, `tests/unit/test_planning.py`.

- **A3 — Restore the `load_events=False` fast path in `list_sessions`.**
  `sqlite_state_repo.py:293` → `[self._row_to_session(r, load_events=False) for r in rows]`.
  Confirms the audit optimization and fixes
  `test_audit_findings.py::...uses_load_events_false`.
  *Verify:* that test + a `list_sessions` smoke assertion.

### Group B — Model catalog / cascade drift  *(Application service, data)*
- **B1 —** Reconcile the role→model cascade with the catalog in
  `weebot/application/services/model_registry/`. For each of the 5 offenders,
  either (a) add the missing model to `_catalog.py` if it is a real, intended
  model, or (b) correct/remove the stale cascade reference. The
  `CatalogValidator` is the source of truth — drive `warning_count` to 0.
  *Verify:* `pytest tests/unit/test_catalog_validator.py`.
  *Note:* touching `_catalog.py` interacts with **D3** — coordinate.

### Group C — Test isolation  *(Test infrastructure)*
- **C1 —** Bisect the polluter (`pytest tests/unit/ -x` narrowing, or
  `pytest-forked` / run halves) — likely a test that reconfigures the root
  logger or mutates the `SecretAccessor` process-global. Fix by adding proper
  teardown: a fixture that snapshots/restores logging handlers & levels and
  resets the `SecretAccessor` singleton, scoped to the offending test (not a
  blanket autouse that hides the real coupling).
  *Verify:* full `pytest tests/unit/` — `test_secret_accessor.py` green in-suite.

### Group D — Architecture-fitness debt  *(cross-layer)*
- **D1 — Remove `weebot/Output/` from the package.** It is build output, not
  source. `git rm -r weebot/Output/`, relocate any example worth keeping under
  `examples/`, and add an ignore rule so generated sites never re-enter the
  package root. *Verify:* `test_no_flat_files_at_root`.

- **D2 — De-couple 3 tools from `WeebotSettings`.** Refactor `berb.py`,
  `reasoner.py`, `scraper.py` to receive their config via the existing
  `ToolConfig` constructor-injection pattern (mirror a compliant tool) instead
  of importing `WeebotSettings` at module import time. This also shrinks the
  settings blast radius. *Verify:* `test_no_settings_import_in_tools`.

- **D3 — `_catalog.py` god module (3792 > 3200).** Preferred: **decompose** the
  catalog into cohesive sub-modules (e.g. by provider/family) re-exported from
  a package `__init__`, keeping the public import path stable. If the catalog is
  intentionally a single generated data table, the alternative is to **raise the
  per-file limit with a documented ADR** and a comment marking it
  generated-data — but decomposition is preferred to keep the fitness gate
  meaningful. Coordinate with **B1**. *Verify:* `test_god_modules_under_800_lines`.

- **D4 — Fix the 3 broken `import-linter` contracts by removing the real edges**
  (not by adding ignores):
  1. **`checkpoint_store → sqlite3`** (Tools-no-DB): the contract flags
     `weebot.tools` reaching a DB via this chain. Trace the `tools → …
     → checkpoint_store` path and route it through a port, or move the
     offending helper out of `weebot.tools`.
  2. **`tool_collection → metrics_bridge → infrastructure.observability.metrics`**
     (Tools-no-infra **and** Interfaces-no-infra both ride this chain). The fix
     is one change with double payoff: make
     `weebot/application/services/metrics_bridge.py` depend on a **metrics
     port** (Application-layer abstraction) instead of importing the concrete
     `infrastructure.observability.metrics`; wire the concrete adapter at the
     composition root (`interfaces`/DI). This removes the
     `application → infrastructure` edge that pulls tools and interfaces across
     the boundary.
  *Verify:* `make lint-imports` → "6 kept, 0 broken"; `test_core_no_application_imports`.

- **D5 — Drive `ignore_imports` from 60 → ≤ 44.** Fixing D4 removes several
  chains; then prune now-dead `ignore_imports` entries in `.importlinter`
  (many are stale/transitive). Target the 44 gate honestly.
  *Verify:* `test_ignore_imports_under_target`.

### Group E — Test & dependency infrastructure  *(hardening)*
- **E1 — Unify test discovery / put the book tests on the CI path.** CI runs
  `tests/unit`, `tests/integration`, `tests/e2e`, but `pytest.ini` sets
  `testpaths = weebot/tests` and the new
  `weebot/tests/unit/test_latex_document.py` therefore **never runs in CI**.
  Decide one canonical tree (recommend the top-level `tests/` that CI already
  targets) and move the LaTeX suite there, or add its path to the workflow.
  The XeLaTeX-gated cases already `skipif(not toolchain_available())`, so
  they stay green on a CI runner without TeX Live (until E4).
- **E2 — Remove dead pytest config.** `pyproject.toml [tool.pytest.ini_options]`
  (`testpaths = ["tests"]`) is silently ignored because `pytest.ini` wins
  (note the "ignoring pytest config in pyproject.toml" warning). Delete the
  duplicate to end the `weebot/tests` vs `tests` ambiguity (align with E1).
- **E3 — Pin the transitive-but-critical deps.** Add explicit
  `pydantic-settings` and `pillow` (Pillow) to `requirements.txt`. They are
  imported directly by first-party code (`weebot/config/settings.py`; 5
  PIL-using modules) yet only arrive transitively today — a future `mcp` or
  `matplotlib` bump could silently drop them.
- **E4 — LaTeX toolchain for the book pipeline (feature-specific, separate).**
  The real compile/preflight tests need XeLaTeX + GFS fonts + poppler-utils +
  Pygments + Ghostscript. Provide them via a dedicated TeX Live build image and
  an opt-in CI job (out of scope for turning the *current* suite green; tracked
  in `tasks/scientific-book-latex-plan.md`).

---

## 5. Sequencing (each phase leaves CI greener)

| Phase | Work | Jobs that go green |
|---|---|---|
| 1 | **A1, A2, A3** | Persistence ✅, CQRS Integration ✅, E2E ✅ (persistence/chaos/concurrent), removes A/A2/A3 unit failures |
| 2 | **B1, C1** | remaining Unit Tests functional failures ✅ (catalog + secret_accessor) |
| 3 | **D4 → D5**, then **D1, D2, D3** | `make lint-imports` ✅, Architecture Fitness ✅ → **Docker Smoke** now actually runs |
| 4 | **E1, E2, E3** | book tests run in CI; config/dep ambiguity removed |
| 5 | **E4** | (separate) real LaTeX compile tests in CI |

After Phase 3, verify **Docker Build Smoke** (previously skipped behind the
gate) genuinely builds and the API `/health` responds — it has never actually
executed, so treat its first green run as new information.

Full gate to call "done":
```bash
make lint-imports                                   # 6 kept, 0 broken
pytest tests/unit/ --cov=weebot --cov-fail-under=48 # green, coverage ≥48%
pytest tests/integration/test_cqrs_handlers.py
pytest tests/e2e/ -m "not external"
```

---

## 6. Risks & mitigations

- **Refactoring `metrics_bridge` to a port (D4)** touches a widely-used path.
  Mitigation: keep the concrete adapter and public call sites identical; only
  invert the import via a thin `MetricsPort` and DI wiring. Land behind the
  full suite.
- **Decomposing `_catalog.py` (D3)** risks changing import paths used by the
  cascade. Mitigation: re-export everything from the package `__init__` so
  `from ..._catalog import X` keeps working; verify with
  `test_catalog_validator` + a grep for import sites.
- **Pruning `ignore_imports` (D5)** can surface a contract that was *masking* a
  real edge. Mitigation: remove entries one at a time, re-running
  `lint-imports` after each.
- **Moving tests (E1)** could double-collect if both trees remain. Mitigation:
  do E1 and E2 together; ensure a single `testpaths`.

---

## 7. PR strategy (recommendation)

These fixes are **unrelated to the scientific-book feature** and touch core
persistence, the model registry, and architecture config. Mixing them into
PR #46 would bloat its diff and couple a feature review to repo-wide debt.

**Recommended:** land this remediation on a **dedicated `chore/ci-stabilization`
branch/PR**, phased as in §5 (Phase 1–2 = "fix failing tests", Phase 3 =
"restore architecture gates", Phase 4 = "test/dep hygiene"). Keep PR #46
focused on the book pipeline; once CI is green on `main`, rebase #46 so it
inherits a green baseline. If a single combined effort is preferred, follow the
same phase order within one branch and call out the split in the PR body.

---

## 8. Out of scope (tracked elsewhere)

- Full XeLaTeX CI image and real compile/preflight jobs (E4) →
  `tasks/scientific-book-latex-plan.md`.
- Opus 4.8 authoring wiring, escalation-ladder Rungs 2–5, CMYK/PDF-X/DPI
  preflight gates, CLI/Web surfaces → same plan.
