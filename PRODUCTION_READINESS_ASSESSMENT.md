# Production Readiness Assessment

**Date:** 2026-07-28
**Commit assessed:** `7a4e084` (main)
**Scope:** Full repository — Python backend (~790 first-party modules), Next.js UI, CI, Docker, docs.

---

## Verdict

The architecture is genuinely good. The **delivery pipeline is not running**, and behind that
silence a core data-access path is broken.

Clean Architecture is real here, not aspirational: all 6 import-linter contracts pass across
843 files and 4,955 dependencies. There are 277 test files and 3,107 passing tests. Security
fundamentals are solid — no `shell=True`, no `eval`/`exec`, a bash guard, an egress guard,
timing-safe token comparison, non-wildcard CORS, and a secret scanner that passes clean.

But **CI has failed on `main` for 30 consecutive runs**, and with nothing enforcing the gates,
regressions landed unnoticed — including one that breaks every session load.

**Not production ready.** The blocking items are concentrated and fixable; most are days, not
months. The correctness blockers (P0) are roughly 1–2 weeks of work.

---

## How this was verified

| Check | Command | Result |
|---|---|---|
| Test suite | `pytest tests/ -m "not external"` (Python 3.12) | **21 failed, 10 errors**, 3107 passed, 143 skipped |
| Coverage | `pytest --cov=weebot` | **52%** (project's own `fail_under` is 60) |
| Architecture | `lint-imports --config .importlinter` | ✅ 6 contracts kept, 0 broken |
| Lint | `ruff check .` | ~10,700 violations, incl. **98 undefined names** in first-party code |
| Custom gates | `make lint-env-access`, `scripts/lint_async_io.py` | ❌ fails; **94 blocking calls in async functions** |
| Dependency CVEs | `pip-audit` | Runtime deps clean (only `pip`/`pytest` toolchain advisories) |
| Frontend CVEs | `npm audit` | **18 advisories, 10 high** |
| Secret scan | `scripts/check-secrets.sh --ci` | ✅ clean |
| CI history | GitHub Actions API, `architecture.yml` on `main` | **30/30 runs failed** |

Two things could not be verified in this sandbox and remain open: the Next.js production build
(`npm ci` was killed mid-install twice) and a live Docker Compose boot.

---

## P0 — Blocks any deployment

### P0-1. Every session load raises `AttributeError`

`weebot/infrastructure/persistence/sqlite_state_repo.py:349` and `:356` call `.get()` on a
row object, but the connection pool sets `row_factory = aiosqlite.Row`
(`connection_pool.py:133`), and `Row` has no `.get()`:

```python
context_raw = json.loads(row.get("context_json") or "{}")   # AttributeError
...
title=row.get("title", ""),                                  # AttributeError
```

`_row_to_session` is the shared tail of both `load_session()` and `list_sessions()`, so session
resume, `GET /api/sessions/{id}`, the session list, and `flow resume` are all dead. Introduced
in `e4fd527` (2026-07-21). Ten tests already catch it — `tests/e2e/test_persistence.py` (5) and
`tests/integration/test_state_manager.py` (5) — and both files are wired into CI jobs that have
not run.

**Fix:** index with `row["..."]`, or convert to `dict(row)` at the top of `_row_to_session`.
Roughly a one-line change; the value is in what it reveals about the gap between "tests exist"
and "tests run."

### P0-2. CI has not executed for 30 runs

Every job in the last 30 `architecture.yml` runs on `main` failed within ~2 seconds, and job
logs return HTTP 404 — the signature of runs that never started (billing/quota, Actions
disabled, or an unresolvable action reference). `Docker Build Smoke Test` is additionally
`needs: architecture-fitness`, so it has been silently *skipped* the whole time.

Every other finding below is downstream of this one. Nothing has been gated since 2026-07-21.

**Fix:** diagnose in the Actions tab (verify billing, Actions permissions, and that
`actions/checkout@v7` / `actions/setup-python@v6` / `docker/setup-buildx-action@v4` resolve),
then make `main` a protected branch requiring the workflow to pass.

### P0-3. 98 undefined names in first-party code

`ruff check --select F821` on `weebot/` + `cli/` (excluding vendored trees) reports 98
`NameError`s waiting to happen. Some are annotation-only and harmless under
`from __future__ import annotations`; several are live:

- `weebot/application/flows/plan_act_flow.py:973` — `_run_span` is a local of a *different*
  method (defined at `:542`). `_maybe_save_checkpoint()` is invoked on every `step` event via
  `session_mutation.py:29`, so the core Plan-Act loop raises on each checkpoint.
- `weebot/application/agents/goal_agent.py:77-78` — `TEMPERATURE_DEFAULT`, `MAX_TOKENS_EXTENDED`
  never imported; `decompose()` raises on every call.
- Same pattern in `structured_executor.py:125`, `synthesizer_agent.py:100`,
  `layer_editor_agent.py:107`, `layer_diagnostics_agent.py:90`, `optimizer_agent.py:139`.
- `weebot/application/di/__init__.py:224` — `TracingAdapter` undefined, breaking tracing setup.
- `weebot/application/agents/executor/_base.py:877` — `recent_tool_signatures` undefined.

**Fix:** triage the 98, fix the live ones, then add `ruff check --select F821 weebot/ cli/` as a
hard CI gate. This class of bug is entirely preventable by lint.

### P0-4. `InMemoryStateRepository` cannot be instantiated

It omits four abstract methods of `StateRepositoryPort` (`save_checkpoint`, `load_checkpoint`,
`delete_checkpoint`, `list_checkpointed_sessions`), so construction raises `TypeError`. This is
why `tests/unit/test_planning.py` fails and it removes the in-memory fallback path entirely.

### P0-5. Model catalog drift breaks role cascades

`test_catalog_validator.py` reports 8 models wired into `ROLE_MODEL_CONFIG` that don't exist in
the catalog — `poolside/laguna-s-2.1`, `meituan/longcat-2.0`, `moonshotai/kimi-k3`,
`google/gemini-3.6-flash`, `thinkingmachines/inkling`, `meta/muse-spark-1.1` — across the
`coder`, `executor`, `reviewer`, `admin`, and `vision` roles. Landed across commits
`25ae52b`..`8553cb5`, all of which had red CI.

### P0-6. `requirements.txt` won't install on the documented Python

`numpy==2.5.1` requires Python ≥3.12, so `pip install -r requirements.txt` fails outright on
3.10/3.11. Meanwhile `pyproject.toml` sets `target-version = "py310"`, and the only statement of
the floor is prose in `README.md` ("Python 3.12+"). There is no machine-readable
`requires-python` anywhere.

**Fix:** add a `[project]` table with `requires-python = ">=3.12"` and align the ruff target.

---

## P1 — Blocks a *professional* deployment

### P1-1. The Compose stack does not start the API

`docker-compose.yml` publishes `8000:8000` for `weebot-api`, but the image's `CMD` is
`python run_mcp.py`, which defaults to `--transport stdio`. No HTTP listener is ever bound. The
container's healthcheck is `python -c "import weebot"` — a separate process that passes
regardless of whether the main process is alive — so Compose reports the service *healthy*
while `weebot-ui` and `weebot-scheduler` wait on it via `condition: service_healthy`.

The CI smoke test cannot catch this: it runs `docker compose up -d --wait || true`, then a
`for` loop of `curl -s ... && break` that never fails the step, and it curls `/health` when the
route is actually `/api/health`.

**Fix:** give `weebot-api` an explicit `command: uvicorn weebot.interfaces.web.main:app --host 0.0.0.0 --port 8000`,
change the healthcheck to `curl -f http://localhost:8000/api/live`, and drop the `|| true` and
the swallowing loop from CI so the smoke test can actually fail.

### P1-2. Container hardening

No `USER` directive — everything runs as root. No `read_only`, no `cap_drop`, no `mem_limit` /
`cpus`, no `security_opt`. Valkey publishes `6379:6379` on the host with no password. For an
agent framework that executes model-directed shell commands, root + unbounded resources is the
wrong default.

### P1-3. Authentication is a single shared static key

`WEEBOT_API_KEY` is one global secret compared against every request
(`main.py` `APIKeyMiddleware`). `auth.py::get_current_user_id` then derives identity as
`f"key-{sha256(api_key)[:16]}"` — but since only one key is ever valid, every caller resolves to
the same user, which makes `verify_session_ownership` a no-op in practice. There is no per-user
issuance, rotation, revocation, expiry, or scoping.

The fail-closed default (503 for non-loopback when no key is set) is a good instinct and worth
keeping. But single-user desktop is the only honest deployment story today — anything
multi-tenant needs real identity first.

### P1-4. No rate limiting

Nothing throttles the HTTP API — no per-IP or per-key limits on session creation, chat, or the
webhook routers (`webhook`, `discord`, `slack`, `whatsapp`), which are internet-facing by
design. Each request can trigger paid LLM calls, so this is a cost-exposure issue as much as an
availability one. There is retry/circuit-breaker logic on the *outbound* LLM side, but nothing
inbound.

### P1-5. Ruff is installed in CI and never invoked

`architecture.yml` runs `pip install import-linter ruff` and then never calls ruff. Repo-wide:
4,873 `W293`, 1,383 `UP045`, 1,024 `E501`, 948 `F401`, 107 `F821`, 72 `F841`. `pre_deploy_cleanup_plan.md`
scoped a cleanup of 82 errors across 6 files; the actual number is two orders of magnitude larger.

### P1-6. `make check` is red and unenforced

CI runs only `make lint-imports` and `make check-arch`. The rest of the project's own gates fail:

- `make lint-env-access` — bare `os.getenv` outside `weebot/config/` in `behavior_integration.py`,
  `cli/ui.py`, `osworld/run_benchmark.py`.
- `scripts/lint_async_io.py` — **94 blocking calls inside async functions** (`ocr.py`,
  `reasoner.py`, `video_ingest_tool.py`, others). Under concurrency these stall the event loop;
  this is the most likely source of latency cliffs in production.

### P1-7. Two conflicting pytest configs

`pytest.ini` sets `testpaths = weebot/tests`; `pyproject.toml` sets `testpaths = ["tests"]`.
`pytest.ini` wins, so a bare `pytest` runs the *wrong* tree — while the Makefile and CI pass
explicit paths and quietly diverge from what a developer gets locally. Delete one.

### P1-8. Coverage is 52% and unmeasured in CI

Below the repo's own `fail_under = 60` in `.coveragerc`. The per-layer targets documented there
(domain 90 / application 80 / infrastructure 70 / tools 65 / interfaces 50) are enforced
nowhere.

### P1-9. The frontend is untested and ungated

Zero test files in `weebot-ui/`. No test runner in `package.json`. CI never runs `npm ci`,
`npm run lint`, `tsc --noEmit`, or `npm run build` — a broken UI build reaches `main` unnoticed.
`npm audit` reports 18 advisories (10 high). `eslint-config-next` is pinned at `14.2.35` against
`next@16.2.10`.

### P1-10. 54 environment variables are undocumented

72 env vars are read across the code; 48 appear in `.env.example`; 54 referenced names are
absent from it. The gap includes security-relevant switches an operator must know about:
`WEEBOT_ADMIN_SECRET`, `WEEBOT_AUTO_APPROVE`, `WEEBOT_EGRESS_ENFORCE`,
`WEEBOT_ENABLE_UNSAFE_MIGRATION_SCRIPTS`, `WEEBOT_ENFORCE_SESSION_OWNERSHIP`,
`WEEBOT_CORS_ORIGIN`, `WEEBOT_DB_BACKEND`. `WeebotSettings` declares 114 fields; there is no
generated reference tying the three together.

### P1-11. No vulnerability scanning in CI

No `pip-audit`, `bandit`, CodeQL, or container scan. `pyproject.toml` configures bandit but
nothing runs it. Dependabot is well configured and is currently the only thing working.

---

## P2 — Operability

### P2-1. The server never configures logging

`configure_logging()` (structlog, JSON renderer) is called from `cli/main.py:124` and nowhere
else. The FastAPI app and the MCP server never call it, so the production surfaces emit
unstructured stdlib logs with no correlation IDs — and `main.py`'s `basicConfig` only runs under
`if __name__ == "__main__"`, which is skipped when uvicorn imports the module. Add the call to
`create_app()` and to `run_mcp.py`.

### P2-2. The schema is not migration-governed

Alembic has 2 revisions covering ~5 tables, while **20 modules issue `CREATE TABLE` at runtime**
(`sqlite_state_repo`, `event_store`, `checkpoint_store`, `skill_store`, `strategy_store`,
`trajectory_repo`, `audit_log`, `scheduler`, …). There is no single source of truth for the
schema and no way to review or roll back most of it.

Compounding this, `main.py`'s lifespan runs `alembic upgrade head` inside the app and downgrades
failure to `logger.warning(...)` — the server boots on an unmigrated database. Migrations belong
in `docker-entrypoint.sh` (where they already are) and should be fatal.

### P2-3. No backup, restore, or DR story

Nothing in `scripts/` or the scheduler backs up the SQLite volume. No documented restore
procedure, no retention policy, no tested recovery. For a system whose entire value is
accumulated session and memory state, this is the largest un-owned operational risk.

### P2-4. SQLite is the scaling ceiling

Single-writer semantics cap concurrent write throughput regardless of process count, so the API
cannot scale horizontally. A PostgreSQL path exists (`persistence/postgresql/`, gated on
`WEEBOT_DB_BACKEND=postgresql`) but is exercised by no test and no CI job. Either commit to it
and test it, or document SQLite's single-node limit explicitly.

### P2-5. Metrics are unreachable when hardened

`/metrics` is not in the `APIKeyMiddleware` skip list, and `/api/prometheus` is not in the
`FailClosedMiddleware` skip list — so with the recommended settings a remote Prometheus cannot
scrape either endpoint. OTEL packages are pinned and present, but the tracing adapter is broken
by P0-3.

### P2-6. `datetime.utcnow()` in the liveness probe

`health.py:393` uses the deprecated `datetime.utcnow()`, which returns a naive timestamp and is
slated for removal. Use `datetime.now(timezone.utc)`.

---

## P3 — Professional polish

### P3-1. Missing standard project files

No `LICENSE` — legally the most consequential omission; without one, nobody may use, copy, or
deploy this. Also missing: `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `CODE_OF_CONDUCT.md`.

### P3-2. No packaging metadata

`pyproject.toml` contains only `[tool.*]` sections — no `[build-system]`, no `[project]`. The
package has no declared name, version, dependencies, or entry points, and `pip install .` does
not work. Versions have already drifted: `VERSION` says `2.3.2`, the FastAPI app says `2.6.0`.

### P3-3. Repository hygiene

- `node_modules/` is committed at the repo root — **2,175 tracked files**.
- `weebot/GitNexus-main/` is 31 MB of vendored third-party code inside the package, including a
  9.6 MB `kuzu-wasm.wasm` and ~15 MB of tree-sitter `.wasm` blobs.
- A 2.2 MB research PDF, `subs.en.vtt` (184 KB), and eleven `transcript*` files sit at the root.
- Windows shell artifacts `$null` and `nul;` are tracked.
- Generated `Output/` artifacts are tracked.
- `.gitignore:82` ignores `/docs/*`, yet ~40 files under `docs/` are tracked anyway — so new
  documentation is silently dropped by `git add` unless force-added. (This report lives at the
  repo root for that reason.)
- **`thunderbird_addressbooks.json` (700 KB) and `abook-2_contacts.json` (85 KB) appear to
  contain personal contact data.** Review these before any public release — removing them
  requires rewriting history, not just a delete commit.

### P3-4. Documentation sprawl

32 markdown files at the repo root plus ~40 in `docs/`, many of them overlapping snapshots:
`ARCHITECTURE_REMEDIATION_PLAN.md`, `ARCHITECTURE_SCORE_9_PLAN.md`, `ARCHITECTURE_AUDIT.md`,
`ARCHITECTURE_ENHANCEMENT_PLAN.md`, `ARCHITECTURE_EXCELLENCE_PLAN.md`,
`ARCHITECTURE_REMEDIATION_PLAN_V2.md`, `FINAL_PRODUCTION_SUMMARY.md`, `PROJECT_COMPLETE.md`,
and a `TODO.md` of 50 KB. There is also a stray `docs/New Text Document.txt`. A newcomer cannot
tell which document is current.

`weebot-ui/README.md` is still the unmodified `create-next-app` boilerplate.

### P3-5. Code style residue

154 `print()` calls in production modules (should be logger calls), mixed CRLF/LF line endings
(visible in `routers/health.py`), and no `.editorconfig` or `.gitattributes` to prevent
recurrence. No pre-commit framework config, though `scripts/check-secrets.sh` is wired as a git
hook.

---

## Recommended sequence

**Phase 1 — Restore the feedback loop (3–5 days)**
1. Fix GitHub Actions so runs execute (P0-2); protect `main` on a passing workflow.
2. Fix `_row_to_session` (P0-1) and `InMemoryStateRepository` (P0-4) — 15 of the 21 failures.
3. Fix the model catalog drift (P0-5).
4. Add `requires-python = ">=3.12"` and a `[project]` table (P0-6, P3-2).
5. Get the suite to zero failures, then make it a required check.

**Phase 2 — Close the correctness gaps (1–2 weeks)**
6. Triage the 98 `F821`s; fix the live ones (P0-3).
7. Add `ruff check --select F,E9` as a blocking gate; schedule the cosmetic backlog separately.
8. Fix the Compose API command and healthcheck; make the docker smoke test able to fail (P1-1).
9. Wire `configure_logging()` into the web and MCP entry points (P2-1).
10. Add `pip-audit` + `bandit` to CI; run `npm audit fix` (P1-11, P1-9).

**Phase 3 — Harden (2–3 weeks)**
11. Replace the shared static key with issued, revocable, per-user credentials (P1-3).
12. Add rate limiting to the API and webhook routers (P1-4).
13. Container hardening: non-root `USER`, resource limits, Valkey auth (P1-2).
14. Work down the 94 async-blocking calls (P1-6).
15. Add UI lint/typecheck/build to CI and a first test (P1-9).
16. Backup + documented, *tested* restore for the data volume (P2-3).

**Phase 4 — Professionalize (1–2 weeks)**
17. `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md` (P3-1).
18. Purge `node_modules/`, vendored blobs, and the contact dumps from history (P3-3).
19. Consolidate the docs to one current set; rewrite the UI README (P3-4).
20. Generate an env-var reference from `WeebotSettings` and regenerate `.env.example` from it,
    checked in CI (P1-10).
21. Raise coverage past the existing 60% floor and enforce it (P1-8).

---

## What is already good

Worth stating plainly, because the problems above are all *process* problems sitting on top of a
sound design:

- **Clean Architecture is genuinely enforced.** Six import-linter contracts over 4,955
  dependencies, all passing, including domain purity and the tools-must-not-touch-persistence
  rule. Most codebases that claim this cannot demonstrate it.
- **Security engineering is thoughtful.** No `shell=True` anywhere. No `eval`/`exec`. A 4-tier
  bash guard, an egress guard, a trust-boundary scanner, a credential sanitizer, timing-safe
  comparison via `hmac.compare_digest`, non-wildcard CORS with credentials, fail-closed remote
  access, and an explicit `--allow-remote` opt-in on the MCP SSE transport that also demands a key.
- **Resilience patterns are real:** circuit breakers with state persisted across restarts, model
  cascading, retries, a connection pool with WAL.
- **3,107 passing tests**, including dedicated adversarial and penetration suites.
- **Dependabot is well configured**, with documented reasoning for each version hold.
- Kubernetes-style `/ready` and `/live` probes, Prometheus metrics, and an ADR directory.

The gap between this design quality and the current runtime state is almost entirely explained
by P0-2. Fix the pipeline first — most of the rest was caught by tests that simply were not run.
