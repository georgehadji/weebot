# Weebot — Production Readiness Implementation Plan

**Version:** 1.0
**Date:** 2026-07-28
**Baseline commit:** `7a4e084` (main)
**Source assessment:** `PRODUCTION_READINESS_ASSESSMENT.md` (PR #48)
**Status:** Proposed — awaiting decisions D-1 and D-2 (§3.6)

---

## 1. Executive Summary

### 1.1 Situation

Weebot is a ~50k-statement Clean Architecture agent framework with a genuinely enforced
hexagonal design: six import-linter contracts pass across 843 modules and 4,955 dependency
edges, 63 ports define the application boundary, and 3,107 tests pass.

It is not deployable today. Three facts define the problem:

1. **CI has not executed since 2026-07-09.** 100+ consecutive runs abort before setup completes.
2. **Session persistence is broken.** Every `load_session()` and `list_sessions()` call raises
   `AttributeError`, disabling session resume, the session API, and `flow resume`.
3. **The defect landed 12 days after CI went dark, and the tests that catch it already existed.**

Fact 3 is the thesis of this plan. This is not a codebase that lacks quality engineering — it is
a codebase whose quality engineering stopped being executed. The remediation is therefore
sequenced to restore enforcement *first*, then repair what enforcement was already catching,
then extend enforcement to the gaps it never covered.

### 1.2 Approach

Four phases, 22 work items, ~7 weeks of single-engineer effort.

| Phase | Theme | Duration | Exit condition |
|---|---|---|---|
| **0** | Restore the feedback loop | 3–5 days | CI green and required on `main` |
| **1** | Close correctness gaps | 1.5–2 weeks | Deployable artifact that boots and serves traffic |
| **2** | Harden | 2.5–3 weeks | Survives hostile input, load, and node loss |
| **3** | Professionalize | 1–1.5 weeks | Legally and operationally shippable |

Phases are strictly ordered by dependency, not by preference. Phase 0 must complete before any
other work merges, because without it no subsequent change can be verified.

### 1.3 Key architectural decisions embedded in this plan

Three findings changed the shape of the remediation relative to the raw defect list:

- **The persistence defect is a contract violation, not a call-site bug.**
  `_SessionQueries.load()` is declared `-> Optional[dict]` but returns `aiosqlite.Row`. Fixing
  the caller (`_row_to_session`) would leave the false contract in place for every future
  consumer. The fix belongs at the boundary that lies. (WI-02)

- **`InMemoryStateRepository` is broken because `StateRepositoryPort` violates ISP.**
  The port carries 11 abstract methods spanning three responsibilities — session CRUD, memory
  salience, and checkpointing — and the four checkpoint methods **duplicate the existing
  standalone `CheckpointPort` verbatim**. Removing them fixes the broken adapter, deletes the
  duplication, and shrinks the port to a coherent responsibility. This is a smaller change than
  implementing four methods on four adapters. (WI-03)

- **`SecretAccessor` already exists and is already the intended seam** for configuration and
  secret access, with redaction built in. The env-var work is completing an existing design, not
  introducing one. (WI-20)

### 1.4 Investment and risk

| | |
|---|---|
| **Total effort** | ~7 weeks, 1 engineer (or ~4 weeks with 2, given Phase 2 parallelism) |
| **Highest-risk item** | WI-11 Authentication — the only change with a breaking API contract |
| **Highest-value item** | WI-01 CI restoration — unblocks verification of all 21 remaining items |
| **Irreversible item** | WI-18 History purge — requires coordinated force-push |
| **Blocked on decision** | WI-17 (schema governance) depends on D-2; scale targets depend on D-1 |

### 1.5 What is deliberately out of scope

Per YAGNI, this plan does **not** propose: a service mesh, Kubernetes manifests, multi-region
deployment, an event-sourcing rewrite, or replacing the LLM adapter layer. The existing
resilience patterns (circuit breakers with persisted state, model cascading, retries) are sound
and are left alone. Scope is confined to what stands between the current tree and a defensible
production deployment.

---

## 2. Current Architecture Assessment

### 2.1 Structure and boundaries

Weebot implements Clean Architecture / Ports & Adapters across four layers:

```
Interfaces  (CLI, FastAPI, MCP, gateways)  →  entry points
     ↓
Infrastructure  (adapters: LLM, persistence, observability, sandbox)
     ↓
Application  (flows, agents, skills, CQRS mediator, 63 ports)
     ↓
Domain  (Pydantic entities, value objects, domain services)
```

Plus a `core/` cross-cutting layer (bash guard, egress guard, model cascade) constrained not to
depend on `application`.

**Verified enforcement.** `lint-imports --config .importlinter` — 6 contracts, 0 broken:

| Contract | Status |
|---|---|
| Domain layer must not depend on outer layers | ✅ |
| Tools must not access databases directly | ✅ |
| Tools must not bypass ports | ✅ |
| Infrastructure must depend on ports, not application services | ✅ |
| Interfaces must not depend on infrastructure adapters directly | ✅ |
| Core must not depend on application | ✅ |

This is the project's strongest asset and the reason remediation is tractable: fixes are
localizable, and the blast radius of any change is bounded by a port.

### 2.2 Dependency and integration surface

- **Inbound:** FastAPI HTTP + WebSocket + SSE; MCP (stdio/SSE); gateways for Telegram, Signal,
  Email/IMAP, Discord, Slack, WhatsApp.
- **Outbound:** OpenRouter, Anthropic, OpenAI, Moonshot, xAI; Playwright/browser-use; Valkey;
  DuckDuckGo; OTLP.
- **Persistence:** SQLite (WAL, pooled) primary; PostgreSQL adapter present behind
  `WEEBOT_DB_BACKEND`; filesystem memory; Valkey event bus (optional, in-memory fallback).

The gateway surface is the widest attack surface and the least protected — six webhook routers
are internet-facing by design and none is rate limited (§2.6).

### 2.3 Data flow

```
Request → Auth middleware → Router → CQRS Mediator → Flow (PlanActFlow)
                                          ↓
                          Planner/Executor agents → LLM port (cascade + breaker)
                                          ↓
                          Middleware pipeline (audit, persistence, session_mutation,
                                                credential_sanitizer, event_bus_publish)
                                          ↓
                          StateRepositoryPort → SQLiteStateRepository → connection pool
                                          ↓
                          EventBus → SSE / WebSocket broadcast
```

**Break point.** The read path `StateRepositoryPort.load_session()` →
`SQLiteStateRepository._row_to_session()` → `_SessionQueries.load()` fails at the last hop. The
write path is intact, so the system accumulates unreadable state — a silent data-availability
failure rather than a loud one.

### 2.4 Scalability

| Dimension | Current ceiling | Constraint |
|---|---|---|
| Concurrent writes | Single writer | SQLite, regardless of process count |
| Horizontal scaling | 1 node | Local SQLite file + in-process scheduler |
| Event loop throughput | Degrades under load | 94 blocking calls inside `async def` |
| Session capacity | Unbounded growth | No retention policy on `events_json` |
| Model cost | Unbounded | No inbound rate limit; each request can trigger paid calls |

`SQLiteStateRepository` stores events as a serialized `events_json` blob per session. Session
size therefore grows without bound and every load deserializes the full history — an O(n) read
that worsens over a session's life. The `load_events=False` optimization the tests expect
(`test_audit_findings.py::test_list_sessions_uses_load_events_false`) is absent from the current
implementation.

### 2.5 Maintainability and technical debt

| Signal | Measured |
|---|---|
| First-party modules | 790 (excl. vendored) |
| Statements | 49,385 |
| Test coverage | **52%** (repo's own floor: 60%) |
| Ruff violations | ~10,700 repo-wide |
| Undefined names (`F821`) in first-party code | **98** |
| Blocking I/O in async functions | **94** |
| `print()` in production modules | 154 |
| Modules issuing runtime `CREATE TABLE` | 20 (vs 2 Alembic revisions) |
| Markdown files | ~70 (32 at repo root) |
| Tracked `node_modules` files | 2,175 |

**Interface Segregation violation.** `StateRepositoryPort` (11 abstract methods) mixes session
CRUD, memory salience queries, and checkpointing. Its four checkpoint methods duplicate the
standalone `CheckpointPort` exactly. Four adapters must implement all 11; one
(`InMemoryStateRepository`, 7 methods) has fallen out of compliance and can no longer be
instantiated. The port's `list_sessions(user_id)` signature has also drifted from the SQLite
implementation's `(user_id, status, limit, offset)` — a Liskov violation that makes the two
non-substitutable.

**Schema governance gap.** Alembic governs ~5 tables; 20 modules create tables at import or
first use. There is no reviewable, roll-back-able definition of most of the schema.

### 2.6 Security posture

**Strong — leave alone:**

- No `shell=True` anywhere in first-party code; no `eval`/`exec`.
- `bash_guard.py` — 4-tier risk classification on all shell execution.
- `egress_guard.py`, `trust_boundary_scanner.py`, `agent_sanitizer.py`,
  `credential_sanitizer` middleware.
- `hmac.compare_digest` for all token comparison (HTTP and WebSocket).
- CORS restricted to an explicit origin list; never wildcard-with-credentials.
- Fail-closed default: remote requests rejected with 503 when no key is configured.
- MCP SSE requires explicit `--allow-remote` *and* a mandatory API key.
- `scripts/check-secrets.sh` passes clean; runs as a pre-commit hook.
- ADR 006 documents the inbound-mail trust boundary.

**Weak:**

| Gap | Consequence |
|---|---|
| Single shared static API key | No per-user identity; `verify_session_ownership` is a no-op in practice since all callers hash to the same ID |
| No rate limiting | Unbounded cost and availability exposure on six internet-facing webhook routers |
| Containers run as root | No `USER`, no `cap_drop`, no resource limits — for a system that executes model-directed shell commands |
| Valkey published without auth | `6379:6379` on the host, no password |
| No CVE scanning in CI | 18 npm advisories (10 high) currently unblocked |
| 54 undocumented env vars | Includes `WEEBOT_ADMIN_SECRET`, `WEEBOT_ENABLE_UNSAFE_MIGRATION_SCRIPTS`, `WEEBOT_AUTO_APPROVE` |

### 2.7 Observability

| Capability | State |
|---|---|
| Structured logging | `configure_logging()` (structlog/JSON) exists but is called **only from the CLI** — web and MCP entry points run unstructured |
| Metrics | Prometheus adapter + `/metrics`; unreachable remotely under recommended auth settings |
| Tracing | OTEL pinned and present; `TracingAdapter` is an undefined name (`di/__init__.py:224`) |
| Health | `/api/health`, `/api/ready`, `/api/live` implemented correctly |
| Audit | `audit_logger.py` + audit middleware present |
| Correlation IDs | Absent from the HTTP path |

### 2.8 CI/CD

One workflow (`architecture.yml`), six jobs. It installs `ruff` and never invokes it. It runs
`make lint-imports` and `make check-arch` but not `make check`, so `lint-env-access` (failing)
and `lint_async_io` (94 violations) are unenforced. Coverage is never measured. The frontend is
never built, linted, type-checked, or tested. The Docker smoke test cannot fail: it uses
`|| true`, a `curl ... && break` loop with no failure branch, and probes `/health` when the route
is `/api/health`.

None of this has run since 2026-07-09.

---

## 3. Detailed Implementation Plan

### 3.1 Phase 0 — Restore the feedback loop (3–5 days)

**Milestone M0: CI green and required on `main`.**

Nothing else merges until this lands. Every downstream item's acceptance criteria depend on a
working pipeline.

| ID | Work item | Effort | Depends on |
|---|---|---|---|
| WI-01 | Restore GitHub Actions execution | 0.5–2d | — |
| WI-02 | Fix session row contract violation | 0.5d | WI-01 |
| WI-03 | Segregate `StateRepositoryPort`; restore `InMemoryStateRepository` | 1d | WI-01 |
| WI-04 | Reconcile model catalog drift | 0.5d | WI-01 |
| WI-05 | Add packaging metadata and Python floor | 0.5d | — |
| WI-06 | Unify pytest configuration | 0.25d | — |

**Exit:** all six jobs pass; suite at 0 failures; branch protection requires the workflow.

### 3.2 Phase 1 — Close correctness gaps (1.5–2 weeks)

**Milestone M1: a deployable artifact that boots and serves traffic.**

| ID | Work item | Effort | Depends on |
|---|---|---|---|
| WI-07 | Remediate 98 `F821`s; add `F,E9` ruff gate | 3d | M0 |
| WI-08 | Fix Compose runtime topology and healthchecks | 1.5d | M0 |
| WI-09 | Configure logging at all entry points; add correlation IDs | 1.5d | M0 |
| WI-10 | Add supply-chain scanning; clear npm advisories | 1d | M0 |

**Exit:** `docker compose up` yields a service that answers `/api/health` and streams events;
CI blocks undefined names and known CVEs.

### 3.3 Phase 2 — Harden (2.5–3 weeks)

**Milestone M2: survives hostile input, sustained load, and node loss.**

| ID | Work item | Effort | Depends on |
|---|---|---|---|
| WI-11 | Replace shared key with per-principal credentials | 5d | M1 |
| WI-12 | Add rate limiting | 2d | M1 |
| WI-13 | Harden containers | 1d | WI-08 |
| WI-14 | Eliminate blocking I/O in async paths | 3d | M1 |
| WI-15 | Add frontend quality gates | 2d | M1 |
| WI-16 | Backup and tested restore | 2d | M1 |
| WI-17 | Bring schema under Alembic governance | 3d | M1, **D-2** |

WI-11/12/13 (security), WI-14 (performance), WI-15 (frontend), WI-16/17 (data) are mutually
independent and parallelizable across engineers.

**Exit:** authenticated multi-principal access; documented load ceiling; restore rehearsed from
a real backup.

### 3.4 Phase 3 — Professionalize (1–1.5 weeks)

**Milestone M3: legally and operationally shippable.**

| ID | Work item | Effort | Depends on |
|---|---|---|---|
| WI-18 | Repository hygiene and history purge | 2d | M2 |
| WI-19 | Add governance files (LICENSE, SECURITY, CONTRIBUTING, CHANGELOG) | 0.5d | — |
| WI-20 | Generate configuration reference from `WeebotSettings` | 1.5d | M1 |
| WI-21 | Raise and enforce coverage floor | 2d | M1 |
| WI-22 | Consolidate documentation | 1d | — |

**Exit:** licensed, documented, reproducible, with coverage enforced above the existing floor.

### 3.5 Dependency graph

```
WI-05 ─┐
WI-06 ─┼─────────────────────────────────────► (independent, land anytime)
WI-19 ─┘
WI-22 ─┘

WI-01 ──┬─► WI-02 ──┐
        ├─► WI-03 ──┼──► M0 ──┬─► WI-07 ──┐
        └─► WI-04 ──┘         ├─► WI-08 ──┼──► M1 ──┬─► WI-11 ─┐
                              ├─► WI-09 ──┤         ├─► WI-12 ─┤
                              └─► WI-10 ──┘         ├─► WI-13 ─┤
                                                    ├─► WI-14 ─┼──► M2 ──► WI-18 ──► M3
                                                    ├─► WI-15 ─┤
                                                    ├─► WI-16 ─┤
                                                    └─► WI-17 ─┘
                                                       (needs D-2)
```

### 3.6 Decisions required before Phase 2

**D-1 — Persistence target and scale envelope.**
SQLite caps the system at one writer and one node. A PostgreSQL adapter exists
(`persistence/postgresql/`) but no test or CI job exercises it.

- *Option A — Stay on SQLite.* Zero migration cost. Requires publishing the single-node limit as
  a supported constraint and deleting or explicitly marking the Postgres adapter experimental.
- *Option B — Promote PostgreSQL.* Enables horizontal scaling. Costs ~1 week: a CI service
  container, adapter parity tests against the port contract, and a data migration path.

*Recommendation: Option A for the first production release,* unless a concrete multi-node
requirement exists. Choosing B for a hypothetical violates YAGNI, and the port abstraction means
the decision stays cheap to revisit.

**D-2 — Schema ownership model.**
20 modules create their own tables outside Alembic.

- *Option A — Full Alembic governance.* Every table in migrations; runtime DDL removed. ~3 days;
  correct; touches 20 modules.
- *Option B — Governed core, autonomous periphery.* Session/event/checkpoint tables under
  Alembic; auxiliary stores (skills, strategies, trajectories) keep runtime DDL behind a
  documented, tested `ensure_schema()` convention. ~1.5 days.

*Recommendation: Option B.* It concentrates rigor where data loss actually matters and avoids a
20-module refactor whose value is largely uniformity. Revisit if the periphery starts holding
durable business state.

---

## 4. Task Breakdown Structure (WBS)

Each item follows: Objective · Affected components · Design changes · Implementation tasks ·
Refactoring · Testing · Acceptance criteria · Rollback.

---

### WI-01 — Restore GitHub Actions execution

**Objective.** Make CI actually execute so every subsequent item is verifiable.

**Affected components.** Repository settings; `.github/workflows/architecture.yml`.

**Design changes.** None to application code. Add branch protection on `main` requiring the
workflow.

**Implementation tasks.**
1. Diagnose in order of likelihood: Actions billing/minutes exhausted → Actions permissions
   disabled on the private repo → runner availability → unresolvable action references.
2. Verify `actions/checkout@v7`, `actions/setup-python@v6`, `docker/setup-buildx-action@v4` all
   resolve; pin to SHAs once confirmed (supply-chain hardening).
3. Trigger a manual run; confirm jobs produce downloadable logs.
4. Enable branch protection: require the workflow, forbid direct pushes to `main`.
5. Add a `concurrency` group to cancel superseded runs.

**Refactoring.** None.

**Testing.** A trivial no-op PR must produce six job results with retrievable logs.

**Acceptance criteria.**
- [ ] All six jobs run to completion with downloadable logs.
- [ ] Job durations are consistent with real work (minutes, not seconds).
- [ ] `main` is protected and requires the workflow to pass.
- [ ] Action references are SHA-pinned.

**Rollback.** Not applicable — restoring a broken pipeline has no regression path. If branch
protection blocks urgent work, it can be lifted per-PR by an admin.

**Risk.** May require account-level access this team does not hold. If billing is the cause and
cannot be resolved, the fallback is self-hosted runners or a temporary mirror on another CI
provider — but this must not be silently deferred, since every other item depends on it.

---

### WI-02 — Fix the session row contract violation

**Objective.** Restore `load_session()` / `list_sessions()`, and eliminate the false type
contract that caused the failure.

**Affected components.**
`weebot/infrastructure/persistence/_session_queries.py` (primary),
`weebot/infrastructure/persistence/sqlite_state_repo.py` (`_row_to_session`),
`weebot/infrastructure/persistence/connection_pool.py` (contract source).

**Design changes.**

The defect is not that `_row_to_session` calls `.get()`. It is that `_SessionQueries` declares
`load() -> Optional[dict]` and `list() -> list[dict]` while returning `aiosqlite.Row` objects,
because the pool sets `row_factory = aiosqlite.Row`. The caller wrote correct code against a
declared contract that the callee does not honor.

Fix at the boundary that lies:

```python
# _session_queries.py
async def load(self, session_id: str) -> Optional[dict]:
    row = await self._pool.execute_read(
        "SELECT * FROM sessions WHERE id = ?", (session_id,), fetch_all=False,
    )
    return dict(row) if row is not None else None

async def list(self, ...) -> list[dict]:
    rows = await self._pool.execute_read(...)
    return [dict(r) for r in rows]
```

`_row_to_session` then needs no change: its `.get()` calls become correct, and the
`title`/`context_json` defaults it relies on start working as intended.

*Rejected alternative:* changing `_row_to_session` to use `row["..."]` indexing. It fixes the
symptom, leaves the false contract for the next consumer, and loses the `.get()` defaults for
nullable columns — reintroducing the bug as a `KeyError` on legacy rows lacking `context_json`.

**Implementation tasks.**
1. Convert `Row` → `dict` at both `_SessionQueries` return sites.
2. Audit sibling query modules for the same pattern (`_behavioral_rule_repo`,
   `_commitment_repo`, `_memory_metadata_repo`).
3. Add the `load_events=False` fast path in `list_sessions` that
   `test_audit_findings.py:204` asserts and the current code lacks.
4. Add a defensive assertion in `_row_to_session` that its argument is a mapping.

**Refactoring.** Consider a shared `_rows_to_dicts()` helper if the pattern recurs across the
audited modules (DRY) — but only if it appears three or more times (YAGNI).

**Testing.**
- Existing: `tests/e2e/test_persistence.py` (5), `tests/integration/test_state_manager.py` (5) —
  all must pass unmodified.
- New: a regression test asserting `_SessionQueries.load()` returns `dict`, not `Row`.
- New: round-trip test for a legacy row with `context_json IS NULL` (the `.get()` default path).
- New: concurrent-save test (closes GAP-1 from `test_gap_analysis.md`).

**Acceptance criteria.**
- [ ] All 10 previously failing persistence tests pass.
- [ ] `_SessionQueries` returns types matching its annotations.
- [ ] A session saved before the fix loads correctly after it (no data migration needed).
- [ ] `list_sessions` skips event deserialization.

**Rollback.** Single-commit revert; no schema or API change. Zero migration risk.

---

### WI-03 — Segregate `StateRepositoryPort`; restore `InMemoryStateRepository`

**Objective.** Make `InMemoryStateRepository` instantiable and remove the port duplication that
broke it.

**Affected components.**
`weebot/application/ports/state_repo_port.py`, `checkpoint_port.py`,
`in_memory_state_repo.py`, `sqlite_state_repo.py`, `postgresql/state_repo.py`,
`legacy_project_adapter.py`, `weebot/application/di/_factories.py`.

**Design changes.**

`StateRepositoryPort` carries 11 abstract methods across three responsibilities. Its four
checkpoint methods (`save_checkpoint`, `load_checkpoint`, `delete_checkpoint`,
`list_checkpointed_sessions`) **duplicate the standalone `CheckpointPort`** (`save`, `load`,
`delete`, `list_checkpointed_sessions`) exactly.

Remove the checkpoint methods from `StateRepositoryPort`. Consumers needing checkpointing depend
on `CheckpointPort`, which already exists and is already injected
(`PlanActFlow._checkpoint_port`).

This is smaller than the alternative — implementing four methods on four adapters — and it
resolves the ISP violation rather than entrenching it.

Also reconcile the Liskov drift: `StateRepositoryPort.list_sessions(user_id)` versus the SQLite
implementation's `(user_id, status, limit, offset)`. Widen the port to the real signature with
defaults.

**Implementation tasks.**
1. Delete the four checkpoint methods from `StateRepositoryPort`.
2. Repoint any consumer using state-repo checkpointing at `CheckpointPort`.
3. Widen `list_sessions` on the port to `(user_id=None, status=None, limit=100, offset=0)`.
4. Verify all four adapters satisfy the reduced port.
5. Add a contract test parameterized over every `StateRepositoryPort` implementation.

**Refactoring.** Evaluate whether the memory-salience methods (`get_low_salience_entries` et al.)
also belong on a separate `MemoryMaintenancePort`. Defer unless it lands within the same day —
ISP is directional, not a mandate to atomize.

**Testing.**
- New: contract test suite run against SQLite, in-memory, and (if D-1 = B) PostgreSQL adapters.
- Existing: `tests/unit/test_planning.py` (2 failures) must pass.
- New: assert `InMemoryStateRepository()` constructs.

**Acceptance criteria.**
- [ ] `InMemoryStateRepository()` instantiates.
- [ ] All four adapters pass one shared contract test.
- [ ] `CheckpointPort` is the sole checkpoint abstraction.
- [ ] `lint-imports` still reports 6/6 contracts kept.

**Rollback.** Revert the port change; adapters remain valid supersets. Low risk — reducing a port
surface cannot break an implementor.

---

### WI-04 — Reconcile model catalog drift

**Objective.** Ensure every model referenced in role cascades exists in the catalog.

**Affected components.** `weebot/config/model_refs.py`, model catalog, `ROLE_MODEL_CONFIG`,
`weebot/application/services/model_selection.py`.

**Design changes.** None structural. `CatalogValidator` already exists and already detects the
drift; it simply is not enforced.

**Implementation tasks.**
1. For each of the 8 orphaned IDs (`poolside/laguna-s-2.1`, `meituan/longcat-2.0`,
   `moonshotai/kimi-k3`, `google/gemini-3.6-flash`, `thinkingmachines/inkling`,
   `meta/muse-spark-1.1`) either add the catalog entry or remove the cascade reference.
2. Verify each surviving ID against the provider's live model list.
3. Promote `test_catalog_validator.py` to a CI gate.
4. Add a startup validation that logs `WARNING` on drift (defensive programming — fail visibly,
   not silently at first inference).

**Refactoring.** None.

**Testing.** `test_catalog_validator.py::test_default_catalog_is_clean` must report 0 warnings.

**Acceptance criteria.**
- [ ] Validator reports 0 warnings across all 60 catalogued models.
- [ ] Every role cascade resolves to at least two live models (primary + fallback).
- [ ] Drift is a CI failure.

**Rollback.** Revert config commit. No runtime state involved.

---

### WI-05 — Add packaging metadata and Python floor

**Objective.** Make the project installable and its runtime requirement machine-readable.

**Affected components.** `pyproject.toml`, `VERSION`, `weebot/interfaces/web/main.py`.

**Design changes.** Add `[build-system]` and `[project]` tables. Establish a single version
source — currently `VERSION` says `2.3.2` while the FastAPI app declares `2.6.0`.

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "weebot"
dynamic = ["version"]
requires-python = ">=3.12"
dependencies = [...]           # promoted from requirements.txt

[project.scripts]
weebot = "cli.main:main"

[tool.setuptools.dynamic]
version = {file = "VERSION"}
```

Set `[tool.ruff] target-version = "py312"` to match reality (currently `py310`, which
contradicts the `numpy==2.5.1` floor).

**Implementation tasks.**
1. Add the tables above; make `VERSION` the single source of truth.
2. Read the app version from package metadata rather than a literal.
3. Align the ruff target to `py312`.
4. Add a CI matrix entry proving `pip install .` succeeds on 3.12.
5. Keep `requirements.txt` as the pinned deployment lockfile; `[project].dependencies` carries
   ranges. Document the distinction.

**Refactoring.** None.

**Testing.** CI job: `pip install .` then `python -c "import weebot; print(weebot.__version__)"`.

**Acceptance criteria.**
- [ ] `pip install .` succeeds from a clean env on 3.12.
- [ ] Installing on 3.11 fails with a clear `requires-python` error rather than a numpy
      resolution wall.
- [ ] One version string, surfaced identically by CLI, API, and package metadata.

**Rollback.** Revert; nothing depends on installability yet.

---

### WI-06 — Unify pytest configuration

**Objective.** Make a bare `pytest` run the same tests as CI.

**Affected components.** `pytest.ini`, `pyproject.toml`.

**Design changes.** Two configs disagree: `pytest.ini` sets `testpaths = weebot/tests`;
`pyproject.toml` sets `testpaths = ["tests"]`. `pytest.ini` wins, so developers running `pytest`
locally exercise a different tree than CI, which passes explicit paths.

Delete `pytest.ini`; consolidate into `[tool.pytest.ini_options]`, preserving the settings only
`pytest.ini` currently carries (`timeout = 60`, `asyncio_default_fixture_loop_scope = session`,
markers, `--strict-markers`).

**Implementation tasks.**
1. Merge all settings into `pyproject.toml`.
2. Delete `pytest.ini`.
3. Reconcile `weebot/tests/` vs `tests/` — determine whether the former is live or vestigial;
   move or delete accordingly.
4. Change CI to invoke `pytest` with markers rather than hardcoded file paths, so new test files
   are picked up automatically.

**Refactoring.** Retire per-file CI invocations in favor of marker selection (`-m "not external"`),
removing the class of failure where a new test file is silently never run.

**Testing.** Bare `pytest` and the CI invocation must collect the same test IDs.

**Acceptance criteria.**
- [ ] Exactly one pytest configuration exists.
- [ ] Local `pytest` and CI collect identical sets.
- [ ] A newly added test file runs in CI without a workflow edit.

**Rollback.** Restore `pytest.ini`. Trivial.

---

### WI-07 — Remediate undefined names; add a ruff gate

**Objective.** Eliminate latent `NameError`s and prevent recurrence.

**Affected components.** ~40 modules across `application/agents`, `application/flows`,
`application/di`, `cli/commands`.

**Design changes.** None architectural. Confirmed live defects include:

| Location | Symbol | Impact |
|---|---|---|
| `flows/plan_act_flow.py:973` | `_run_span` | Local of a different method (`:542`); raises on every checkpoint save, invoked per `step` event via `session_mutation.py:29` — the core Plan-Act loop |
| `agents/goal_agent.py:77-78` | `TEMPERATURE_DEFAULT`, `MAX_TOKENS_EXTENDED` | `decompose()` raises on every call |
| `agents/structured_executor.py:125` | `TEMPERATURE_DEFAULT` | Structured execution path |
| `agents/synthesizer_agent.py:100-101` | temperature/token constants | Synthesis path |
| `di/__init__.py:224` | `TracingAdapter` | Breaks tracing wiring |
| `agents/executor/_base.py:877` | `recent_tool_signatures` | Executor loop |

`_run_span` is the most serious: it indicates a span lifecycle split across methods without
shared state. Fix by moving span management into the tracing collaborator rather than
threading a local through the class — the alternative (promoting it to `self._run_span`) works
but leaks tracing state onto the flow object.

**Implementation tasks.**
1. Generate the full inventory: `ruff check weebot/ cli/ --select F821 --output-format=concise`.
2. Triage into: (a) annotation-only under `from __future__ import annotations` — harmless, fix by
   adding the import; (b) missing imports — add them; (c) genuine logic errors — fix and add a
   regression test each.
3. Fix `_run_span` by relocating span lifecycle to the tracing collaborator.
4. Add CI gate: `ruff check weebot/ cli/ --select F,E9`.
5. File the ~10,600 cosmetic violations as separate scheduled work; do **not** bundle them here —
   a 10k-line diff would make the correctness fixes unreviewable.

**Refactoring.** Extract shared LLM parameter constants (`TEMPERATURE_*`, `MAX_TOKENS_*`) into
one module and import consistently (DRY) — their absence in six agents indicates a refactor that
was applied unevenly.

**Testing.**
- New: a smoke test per affected agent that calls the previously broken method with a mocked LLM.
- New: an integration test driving `PlanActFlow` through a checkpoint save.
- Gate: `ruff --select F,E9` clean.

**Acceptance criteria.**
- [ ] 0 `F821` in `weebot/` and `cli/`.
- [ ] `GoalAgent.decompose()`, `PlanActFlow._maybe_save_checkpoint()`, and the tracing wiring all
      execute under test.
- [ ] CI fails on any new undefined name.

**Rollback.** Per-module revert; changes are independent. Low risk — most edits are added imports.

---

### WI-08 — Fix Compose runtime topology and healthchecks

**Objective.** Make the deployed artifact actually serve HTTP, and make its health signal
meaningful.

**Affected components.** `docker-compose.yml`, `Dockerfile`, `docker-entrypoint.sh`,
`.github/workflows/architecture.yml`.

**Design changes.**

`weebot-api` publishes `8000:8000` but its `CMD` is `python run_mcp.py`, which defaults to
`--transport stdio`. No HTTP listener binds. Its healthcheck is `python -c "import weebot"` — a
separate process that passes regardless of whether the server process is alive — so Compose
reports the service healthy while `weebot-ui` and `weebot-scheduler` gate on it via
`condition: service_healthy`.

Separate the two runtimes into distinct services with honest healthchecks:

```yaml
weebot-api:
  command: ["uvicorn", "weebot.interfaces.web.main:app",
            "--host", "0.0.0.0", "--port", "8000"]
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/api/live"]
    interval: 30s
    timeout: 5s
    retries: 3
    start_period: 20s

weebot-mcp:
  command: ["python", "run_mcp.py", "--transport", "sse",
            "--host", "0.0.0.0", "--port", "5050", "--allow-remote"]
```

Note `--allow-remote` requires `WEEBOT_MCP_API_KEY` (already enforced in `run_mcp.py`) — correct
existing behavior, now exercised.

Move migrations fully into `docker-entrypoint.sh` (already there) and **remove the in-app
`alembic upgrade head`** from the FastAPI lifespan, where its failure is downgraded to a warning
and the server boots on an unmigrated database.

**Implementation tasks.**
1. Split `weebot-api` / `weebot-mcp`; give each an explicit command.
2. Replace both healthchecks with real endpoint probes; install `curl` in the runtime image.
3. Delete the lifespan migration block; make entrypoint migration failure fatal.
4. Fix the CI smoke test: remove `|| true`, probe `/api/health`, fail the job on a non-2xx after
   a bounded retry budget.
5. Remove `needs: architecture-fitness` from the docker job, or keep it — but note it has been
   silently skipping for 100+ runs; make skips visible.
6. Add `depends_on` conditions that reflect the corrected health semantics.

**Refactoring.** None.

**Testing.**
- CI: `docker compose up -d --wait`, then assert `/api/health` returns 200 and `/api/live`
  returns `{"alive": true}`.
- New: assert the smoke test *fails* when the API is deliberately misconfigured (test the test).

**Acceptance criteria.**
- [ ] `docker compose up` yields a listener on 8000 answering `/api/health`.
- [ ] Healthcheck reports unhealthy when the server process is killed.
- [ ] CI smoke test fails on a broken image.
- [ ] Migration failure prevents startup rather than warning.

**Rollback.** Revert compose/Dockerfile changes; images are rebuilt per deploy, so rollback is a
redeploy of the prior tag.

---

### WI-09 — Configure logging at all entry points

**Objective.** Give the production surfaces the structured logging the CLI already has.

**Affected components.** `weebot/interfaces/web/main.py`, `run_mcp.py`,
`weebot/infrastructure/observability/logging_config.py`, HTTP middleware.

**Design changes.** `configure_logging()` is called only from `cli/main.py:124`. `main.py`'s
`logging.basicConfig` sits under `if __name__ == "__main__"`, which uvicorn skips when importing
the module. The web and MCP servers therefore run with stdlib defaults and no correlation.

Call `configure_logging()` from `create_app()` and from `run_mcp.main()`. Add a correlation-ID
middleware that accepts an inbound `X-Request-ID` or generates one, binds it to the structlog
context, and echoes it on the response.

**Implementation tasks.**
1. Invoke `configure_logging()` in `create_app()` and `run_mcp.main()`.
2. Add `CorrelationIdMiddleware`; bind via `structlog.contextvars`.
3. Propagate the correlation ID into flow events and LLM adapter logs.
4. Make log level configurable (`WEEBOT_LOG_LEVEL`) via `SecretAccessor`.
5. Replace `print()` in the ~15 highest-traffic production modules with logger calls; schedule
   the remaining ~139 as follow-up.
6. Fix `datetime.utcnow()` → `datetime.now(timezone.utc)` in `health.py:393`.

**Refactoring.** Add a `lint-no-print` Makefile target mirroring the existing custom gates.

**Testing.**
- New: assert the app emits JSON-formatted logs under test.
- New: assert an inbound `X-Request-ID` appears in log output and the response header.

**Acceptance criteria.**
- [ ] Web and MCP servers emit structured JSON logs.
- [ ] Every HTTP response carries `X-Request-ID`.
- [ ] A single request is traceable end-to-end by correlation ID.
- [ ] No secrets in logs (verified against `SecretAccessor` redaction).

**Rollback.** Revert; logging changes carry no data risk.

---

### WI-10 — Add supply-chain scanning

**Objective.** Fail the build on known-vulnerable dependencies.

**Affected components.** `.github/workflows/architecture.yml`, `pyproject.toml`,
`weebot-ui/package.json`.

**Design changes.** Add a `security` job running `pip-audit`, `bandit` (already configured in
`pyproject.toml` but never invoked), and `npm audit`.

**Implementation tasks.**
1. Add the `security` job; run on PR and a weekly schedule.
2. `pip-audit -r requirements.txt --strict`.
3. `bandit -c pyproject.toml -r weebot/ cli/`.
4. `npm audit --audit-level=high` in `weebot-ui`.
5. Resolve the current 18 npm advisories (10 high) via `npm audit fix`.
6. Align `eslint-config-next` (14.2.35) with `next` (16.2.10).
7. Establish a documented exception process for accepted advisories (an allowlist file with an
   expiry date per entry — never a blanket `--ignore`).

**Refactoring.** None.

**Testing.** Verify the job fails against a deliberately pinned vulnerable package.

**Acceptance criteria.**
- [ ] `pip-audit`, `bandit`, `npm audit` all run in CI and can fail it.
- [ ] 0 high/critical advisories, or each documented with an expiry.
- [ ] Weekly scheduled scan catches newly disclosed CVEs between PRs.

**Rollback.** Downgrade the job to non-blocking (`continue-on-error`) if it destabilizes the
pipeline — but with a dated ticket to restore, never indefinitely.

---

### WI-11 — Replace the shared key with per-principal credentials

**Objective.** Establish real identity so authorization means something.

**Affected components.** `weebot/interfaces/web/auth.py`, `main.py` middleware,
`weebot/config/settings.py`, new `ApiKeyPort` + adapter, Alembic migration, `weebot-ui` client.

**Design changes.**

Today `WEEBOT_API_KEY` is a single global secret. `get_current_user_id()` derives identity as
`sha256(key)[:16]` — but since only one key is ever valid, every caller resolves to the same
principal, making `verify_session_ownership()` a no-op. The design *anticipates* multi-principal
identity; the implementation never delivered it.

Introduce a credential store behind a port, consistent with the existing hexagonal design:

```
weebot/application/ports/api_key_port.py        # new port
weebot/infrastructure/security/sqlite_api_key_store.py   # adapter
```

- Keys stored as salted hashes (Argon2id or scrypt), never plaintext.
- Each key: `id`, `principal_id`, `hash`, `scopes`, `created_at`, `expires_at`, `revoked_at`,
  `last_used_at`.
- `get_current_user_id()` resolves via the store and returns the real `principal_id`.
- Retain `hmac.compare_digest` semantics; the store lookup must be constant-time with respect to
  key validity (hash comparison, not a short-circuit existence check).
- CLI: `weebot auth create-key --principal <id> --scopes <...> --expires <duration>`.

**Backward compatibility.** Keep `WEEBOT_API_KEY` working as a bootstrap admin credential for one
minor version, emitting a deprecation warning on each use. This preserves single-user desktop
deployments while the multi-principal path matures.

**Implementation tasks.**
1. Define `ApiKeyPort`; implement the SQLite adapter; register in DI.
2. Alembic migration for the `api_keys` table (this table is core — Alembic-governed under D-2
   Option B).
3. Rewrite `APIKeyMiddleware` to resolve through the port.
4. Rewrite `get_current_user_id()` to return the resolved principal.
5. Add CLI key management (create, list, revoke).
6. Retain and deprecate the env-var bootstrap path.
7. Update the UI client to send its key unchanged (no client change required).
8. Add scope checks on mutating endpoints, replacing `require_mutation_identity`'s loopback
   heuristic.

**Refactoring.** `verify_session_ownership()` becomes genuinely enforcing. Audit every route for
the ownership dependency — `chat_router.py` was flagged as missing it in
`pre_deploy_cleanup_plan.md` (DB-3) and never fixed.

**Testing.**
- New: unit tests for issuance, hashing, expiry, revocation.
- New: security tests — expired key rejected, revoked key rejected, principal A cannot read
  principal B's session (currently unenforceable).
- New: timing-attack test on key validation.
- Existing: `test_security_penetration.py` must still pass.
- New: backward-compat test for the deprecated env-var path.

**Acceptance criteria.**
- [ ] Two principals with distinct keys cannot see each other's sessions.
- [ ] Expired and revoked keys are rejected.
- [ ] Keys are never stored or logged in plaintext.
- [ ] `WEEBOT_API_KEY` still works and warns.
- [ ] `/api/health`, `/api/live` remain unauthenticated; `/metrics` becomes reachable by a
      scoped metrics principal.

**Rollback.** Feature-flag behind `WEEBOT_AUTH_MODE=legacy|store`, defaulting to `legacy` for one
release. Rollback is a config change, not a redeploy. The migration is additive — the `api_keys`
table is inert under `legacy`.

**Risk.** Highest of any item: the only change with a breaking API contract. Mitigated by the
flag, the deprecation window, and additive-only schema.

---

### WI-12 — Add rate limiting

**Objective.** Bound cost and availability exposure on public endpoints.

**Affected components.** `weebot/interfaces/web/main.py`, all routers, especially the six
webhook routers; Valkey.

**Design changes.** Middleware-based token bucket, keyed by principal (post-WI-11) falling back
to client IP. Valkey-backed when available, in-memory otherwise — mirroring the existing event
bus's optional-Valkey pattern.

Tiered limits, since endpoint costs differ by orders of magnitude:

| Class | Endpoints | Suggested limit |
|---|---|---|
| Health | `/api/health`, `/api/live`, `/api/ready` | unlimited |
| Read | session list/get, models | 120/min |
| Mutating | session create, chat | 20/min |
| Webhook | discord, slack, whatsapp, telegram | 60/min per source |
| Expensive | flow run | 10/min, plus a concurrency cap |

Return `429` with `Retry-After` and `X-RateLimit-*` headers. Emit
`weebot_rate_limits_hit_total` — the metric name already exists in `metrics.py:74` for MCP and
should be generalized.

**Implementation tasks.**
1. Implement `RateLimitMiddleware` with a pluggable backend.
2. Valkey backend (sliding window) + in-memory fallback.
3. Per-route configuration via decorator or route metadata.
4. Wire the existing `RATE_LIMIT_EXCEEDED` audit event (`audit_logger.py:60`).
5. Add a global concurrency cap on flow execution to bound LLM spend.
6. Document limits in the API reference.

**Refactoring.** None.

**Testing.**
- New: unit tests for bucket refill and boundary conditions.
- New: integration test asserting 429 after N requests and recovery after the window.
- New: load test confirming limits hold under concurrency.
- New: assert health endpoints are never limited (must not break k8s probes).

**Acceptance criteria.**
- [ ] Exceeding a limit returns 429 with `Retry-After`.
- [ ] Limits are per-principal, not global.
- [ ] Health/liveness are exempt.
- [ ] Limit hits are metered and audited.
- [ ] Valkey outage degrades to in-memory, never to fail-open-unbounded.

**Rollback.** Env-var kill switch (`WEEBOT_RATE_LIMIT_ENABLED=false`). No persistent state.

---

### WI-13 — Harden containers

**Objective.** Reduce blast radius of a compromised agent process.

**Affected components.** `Dockerfile`, `Dockerfile.api`, `Dockerfile.web`, `docker-compose.yml`.

**Design changes.** The container runs as root with no resource bounds — for a system that
executes model-directed shell commands. Add a non-root user, drop capabilities, bound resources,
and authenticate Valkey.

```dockerfile
RUN groupadd -r weebot && useradd -r -g weebot -u 10001 weebot \
 && mkdir -p /app/data && chown -R weebot:weebot /app
USER weebot
```

```yaml
weebot-api:
  user: "10001:10001"
  read_only: true
  tmpfs: [/tmp]
  cap_drop: [ALL]
  security_opt: [no-new-privileges:true]
  deploy:
    resources:
      limits: {cpus: "2.0", memory: 4G}

weebot-valkey:
  command: ["valkey-server", "--requirepass", "${VALKEY_PASSWORD:?required}"]
  ports: []          # internal network only
```

**Implementation tasks.**
1. Add non-root user to all three Dockerfiles; fix volume ownership.
2. Verify Playwright/Chromium runs non-root (may need `--no-sandbox` — evaluate the tradeoff
   against the existing sandbox abstraction rather than adding it reflexively).
3. Apply `read_only`, `tmpfs`, `cap_drop`, `no-new-privileges`, resource limits.
4. Enable Valkey auth; remove its host port publication.
5. Add container image scanning (Trivy) to the security job from WI-10.

**Refactoring.** None.

**Testing.**
- CI: assert the container's effective UID is not 0.
- CI: full smoke test must still pass under the hardened profile.
- New: verify writes outside `/app/data` and `/tmp` fail.

**Acceptance criteria.**
- [ ] No container runs as root.
- [ ] Resource limits enforced.
- [ ] Valkey requires a password and is not host-published.
- [ ] Image scan reports no high/critical OS CVEs.
- [ ] Browser automation still functions.

**Rollback.** Revert compose profile; redeploy prior image tag.

**Risk.** Playwright frequently requires elevated privileges. If non-root browser execution
proves infeasible, isolate browser work into a separate, differently-privileged service rather
than relaxing the whole stack.

---

### WI-14 — Eliminate blocking I/O in async paths

**Objective.** Remove event-loop stalls that cap concurrent throughput.

**Affected components.** 94 sites; concentrated in `weebot/tools/` (`ocr.py`, `reasoner.py`,
`video_ingest_tool.py`) plus adapters.

**Design changes.** Synchronous file, image, and subprocess operations inside `async def` block
the loop for every other in-flight request. Wrap in `asyncio.to_thread()`, or use `aiofiles`
(already a dependency) for file I/O.

**Implementation tasks.**
1. Inventory via `python scripts/lint_async_io.py`.
2. Triage by hot-path impact — fix request-path sites first, startup-only sites last.
3. Convert file I/O to `aiofiles`; CPU-bound work (PIL, OCR) to `asyncio.to_thread`.
4. Add `make lint-async-io` to CI as a blocking gate once the count reaches 0.
5. Add a ratchet: the gate fails if the count increases, allowing incremental progress if a full
   sweep proves impractical.

**Refactoring.** Tools performing heavy CPU work may warrant a process pool rather than a thread
pool. Evaluate after measurement — do not pre-optimize.

**Testing.**
- New: latency benchmark — p99 under 50 concurrent sessions, before vs after.
- Existing: `TestConcurrentFlows` must pass and should improve.
- Gate: `lint_async_io` reports 0.

**Acceptance criteria.**
- [ ] 0 violations, or a ratcheted count that cannot increase.
- [ ] Measured p99 latency improvement under concurrency.
- [ ] No functional regressions in the affected tools.

**Rollback.** Per-module revert; each conversion is independent.

---

### WI-15 — Add frontend quality gates

**Objective.** Stop shipping an unverified UI.

**Affected components.** `weebot-ui/`, CI.

**Design changes.** The frontend has zero tests, no CI, and a `README.md` that is still
unmodified `create-next-app` boilerplate. Add a `frontend` CI job running install, lint,
typecheck, build, and test.

**Implementation tasks.**
1. Add the `frontend` job: `npm ci`, `npm run lint`, `tsc --noEmit`, `npm run build`.
2. Add Vitest + React Testing Library; write smoke tests for the session view, chat, and the
   WebSocket client.
3. Add a Playwright E2E test covering login → create session → observe streamed events.
4. Resolve npm advisories (coordinated with WI-10).
5. Rewrite `weebot-ui/README.md`.

**Refactoring.** Extract the API client into a typed module if not already isolated, so contract
changes surface at compile time.

**Testing.** The job itself is the deliverable. Target ≥40% component coverage initially —
a floor to ratchet, not an end state.

**Acceptance criteria.**
- [ ] CI builds the UI on every PR.
- [ ] Lint and typecheck pass.
- [ ] At least one E2E test covers the primary user journey.
- [ ] README describes weebot, not `create-next-app`.

**Rollback.** Mark the job non-blocking; the tests remain valuable.

**Note.** The production build could not be verified during assessment (`npm ci` was killed twice
in a constrained sandbox). Confirm it builds before scoping test work — if it does not, that
becomes a P0 item ahead of this one.

---

### WI-16 — Backup and tested restore

**Objective.** Make data loss recoverable.

**Affected components.** New `scripts/backup.py`, `weebot/scheduling/default_jobs.py`, docs.

**Design changes.** Nothing backs up the SQLite volume today — the largest un-owned risk, since
accumulated session and memory state *is* the product's value. Add a scheduled job using
SQLite's online backup API (safe against a live WAL database, unlike `cp`).

- Daily full backup; configurable retention (default 30 days).
- Integrity verification (`PRAGMA integrity_check`) on each artifact.
- Optional off-host destination via `file_storage_port` (the port already exists).
- Emit `weebot_backup_last_success_timestamp` for alerting on staleness.

**Implementation tasks.**
1. `scripts/backup.py` using `sqlite3.Connection.backup()`.
2. Register a scheduled job alongside the existing session-health and memory-compaction jobs.
3. `scripts/restore.py` with an explicit confirmation prompt.
4. Retention/pruning.
5. Document the runbook in `docs/RESILIENCE_AND_DEPLOYMENT.md` (already exists).
6. Emit backup metrics.

**Refactoring.** None.

**Testing.**
- New: backup → corrupt the original → restore → assert data equality.
- New: verify a backup taken during concurrent writes is consistent.
- **Rehearsal:** perform one restore manually and record elapsed time as the RTO baseline.

**Acceptance criteria.**
- [ ] Backups run on schedule and are integrity-verified.
- [ ] Restore has been executed at least once, end to end, from a real artifact.
- [ ] RPO and RTO are documented numbers, not aspirations.
- [ ] Backup staleness is alertable.

**Rollback.** Disable the scheduled job. Backups are additive and cannot harm the primary.

---

### WI-17 — Bring schema under Alembic governance

**Objective.** Make the durable schema reviewable and reversible. *(Depends on D-2.)*

**Affected components.** `alembic/versions/`, `sqlite_state_repo.py`, `event_store.py`,
`checkpoint_store.py`, `gateway_session_store.py`, `_session_queries.py`.

**Design changes.** Under **D-2 Option B** (recommended): bring the core durable tables —
sessions, events, checkpoints, gateway sessions, api_keys (WI-11) — under Alembic and remove
their runtime DDL. Auxiliary stores (skills, strategies, trajectories, posteriors) retain runtime
DDL behind a documented `ensure_schema()` convention with a contract test.

**Implementation tasks.**
1. Inventory all 20 runtime-DDL modules; classify core vs auxiliary.
2. Write migrations capturing the current core schema exactly (verify against a live DB — a
   migration that diverges from production reality is worse than none).
3. Remove runtime DDL from core modules.
4. Add a CI check that a fresh `alembic upgrade head` produces a schema identical to the one the
   application expects.
5. Formalize `ensure_schema()` for auxiliary stores; add a contract test.
6. Document the split and its rationale in an ADR.

**Refactoring.** Standardize `ensure_schema()` across auxiliary stores (DRY).

**Testing.**
- New: fresh-database migration test.
- New: upgrade-from-existing-database test using a real pre-migration snapshot.
- New: downgrade test for each revision.
- New: schema-drift detection.

**Acceptance criteria.**
- [ ] Core tables are Alembic-governed; no runtime DDL for them.
- [ ] `alembic upgrade head` on an empty DB yields a working schema.
- [ ] Every revision downgrades cleanly.
- [ ] Drift fails CI.

**Rollback.** Migrations must be individually reversible — this is the acceptance criterion, not
an afterthought. Take a backup (WI-16) before applying in any environment holding real data.

**Risk.** Highest data risk in the plan. Sequenced after WI-16 deliberately, so a tested restore
path exists before schema changes touch real data.

---

### WI-18 — Repository hygiene and history purge

**Objective.** Make the repository reproducible, portable, and free of inappropriate content.

**Affected components.** Git history, `.gitignore`, repo root.

**Design changes.** Remove from tracking and from history: `node_modules/` (2,175 files), vendored
`weebot/GitNexus-main/` binary assets (~31 MB, incl. a 9.6 MB `.wasm`), a 2.2 MB PDF,
transcript artifacts, Windows shell junk (`$null`, `nul;`), and generated `Output/`.

**Handle with care:** `thunderbird_addressbooks.json` (700 KB) and `abook-2_contacts.json` (85 KB)
appear to contain **personal contact data**. Removing them requires history rewriting, and if the
repository was ever public or shared, may carry data-protection notification obligations. Review
before acting.

Also fix `.gitignore:82`, which ignores `/docs/*` while ~40 files under `docs/` are tracked —
so new documentation is silently dropped by `git add`.

**Implementation tasks.**
1. Review the contact files; determine provenance and obligations. Escalate if the repo was ever
   public.
2. Replace vendored GitNexus with a pinned dependency or submodule; if it must stay, move it out
   of the installable package.
3. Purge with `git-filter-repo`; coordinate a scheduled force-push.
4. Fix `.gitignore` (`/docs/*` rule) and add `.gitattributes` for line endings (CRLF is present
   in `routers/health.py`).
5. Add `.editorconfig`.
6. Notify all contributors to re-clone.

**Refactoring.** None.

**Testing.** Post-rewrite: clean clone, install, full suite green.

**Acceptance criteria.**
- [ ] Clone size reduced by >40 MB.
- [ ] No dependency directories or generated artifacts tracked.
- [ ] Personal data removed from history, with the decision documented.
- [ ] `.gitignore` no longer contradicts tracked content.
- [ ] Full suite passes on a fresh clone.

**Rollback.** **Effectively irreversible after force-push.** Mandatory: a full mirror clone
retained off-host before rewriting. Schedule during a quiet window with all contributors
notified.

**Risk.** Highest coordination risk in the plan. Sequenced last deliberately — a history rewrite
mid-project would invalidate every open branch.

---

### WI-19 — Add governance files

**Objective.** Make the project legally and procedurally usable.

**Affected components.** Repo root.

**Design changes.** Add `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`,
`CODE_OF_CONDUCT.md`.

Absence of a `LICENSE` is the single most consequential omission in the repository: with no
license, no one — including customers and contributors — has any right to use, copy, modify, or
deploy the software. Default copyright reserves all rights.

**Implementation tasks.**
1. Choose a license (owner's decision; consider dependency compatibility — Valkey is BSD-3).
2. `SECURITY.md`: reporting channel, supported versions, response SLA.
3. `CONTRIBUTING.md`: setup, branch policy, commit conventions (the repo already uses
   Conventional Commits), review standards, required gates.
4. `CHANGELOG.md` in Keep a Changelog format, seeded from git history.
5. Add a PR template — none exists.

**Refactoring.** None.

**Testing.** Not applicable.

**Acceptance criteria.**
- [ ] `LICENSE` present and referenced in package metadata.
- [ ] Security reporting channel documented.
- [ ] Contribution workflow documented and matching enforced CI.
- [ ] Changelog covers at least the current major version.

**Rollback.** Not applicable.

---

### WI-20 — Generate a configuration reference

**Objective.** Make every configuration knob discoverable and documented.

**Affected components.** `weebot/config/settings.py`, `secret_accessor.py`, `.env.example`,
new `scripts/generate_config_reference.py`.

**Design changes.** 72 env vars are read in code; 48 appear in `.env.example`; **54 referenced
names are absent from it** — including `WEEBOT_ADMIN_SECRET`, `WEEBOT_AUTO_APPROVE`,
`WEEBOT_EGRESS_ENFORCE`, `WEEBOT_ENABLE_UNSAFE_MIGRATION_SCRIPTS`,
`WEEBOT_ENFORCE_SESSION_OWNERSHIP`. `WeebotSettings` declares 114 fields. Three sources of truth,
none authoritative.

Make `WeebotSettings` + `SecretAccessor` the single source and generate the rest. The pattern
already exists: `scripts/generate_capabilities_schema.py` does this for capabilities.

**Implementation tasks.**
1. Ensure every setting has a `Field(description=...)`, a default, and a sensitivity marker.
2. Write `scripts/generate_config_reference.py` emitting `docs/CONFIGURATION.md` and
   `.env.example`.
3. Add `make generate-config` alongside the existing `make generate-capabilities`.
4. CI check: regenerate and fail if the committed output differs (same pattern as generated
   schemas).
5. Complete the `SecretAccessor` migration — `make lint-env-access` currently fails on
   `behavior_integration.py`, `cli/ui.py`, `osworld/run_benchmark.py` — then make it a CI gate.
6. Mark deprecated/experimental flags explicitly, especially
   `WEEBOT_ENABLE_UNSAFE_MIGRATION_SCRIPTS`.

**Refactoring.** Route the remaining bare `os.getenv` calls through `SecretAccessor`, completing
the design its own docstring describes as mandatory.

**Testing.**
- New: assert every env var referenced in code appears in generated docs.
- New: assert `.env.example` is regenerable and current.
- Gate: `make lint-env-access` passes.

**Acceptance criteria.**
- [ ] 0 undocumented env vars.
- [ ] `.env.example` is generated, not hand-maintained.
- [ ] Drift fails CI.
- [ ] `lint-env-access` passes and is enforced.

**Rollback.** Revert generation; hand-maintained files remain valid.

---

### WI-21 — Raise and enforce the coverage floor

**Objective.** Convert coverage from an aspiration into a gate.

**Affected components.** `.coveragerc`, CI, test suites.

**Design changes.** Coverage is 52% against the repo's own `fail_under = 60`, and is never
measured in CI. `.coveragerc` documents per-layer targets (domain 90 / application 80 /
infrastructure 70 / tools 65 / interfaces 50) enforced nowhere.

Measure in CI, enforce the existing 60% floor, then ratchet toward the documented per-layer
targets. Do not jump straight to 90% — a large, hastily written test batch buys coverage without
confidence.

**Implementation tasks.**
1. Add coverage measurement to the unit-test job; upload the report as an artifact.
2. Enforce `fail_under = 60` immediately (an 8-point climb).
3. Close the gaps from `test_gap_analysis.md`: concurrent session saves (GAP-1), pool exhaustion
   (GAP-2), scheduler double-execution (GAP-3), E2E flow with mocked LLM (GAP-4).
4. Add per-layer enforcement, starting with domain (highest value, easiest to test — it is pure).
5. Ratchet the floor by 5 points per iteration until per-layer targets are met.
6. Add coverage diff reporting on PRs.

**Refactoring.** Address the test-isolation issue flagged in `test_gap_analysis.md` — module-level
singletons (`_SETTINGS`, `_pool_registry`) block parallel execution and will matter as the suite
grows.

**Testing.** Meta-work; the deliverable is the gate.

**Acceptance criteria.**
- [ ] Coverage measured on every PR.
- [ ] Global floor enforced and passing.
- [ ] Domain layer ≥90%.
- [ ] All four documented gaps closed.
- [ ] Coverage cannot decrease.

**Rollback.** Lower the floor to the current measured value; never remove the gate.

---

### WI-22 — Consolidate documentation

**Objective.** Make it possible to tell which document is current.

**Affected components.** ~70 markdown files.

**Design changes.** 32 files at the repo root plus ~40 in `docs/`, with heavy overlap:
`ARCHITECTURE_REMEDIATION_PLAN.md`, `ARCHITECTURE_SCORE_9_PLAN.md`, `ARCHITECTURE_AUDIT.md`,
`ARCHITECTURE_ENHANCEMENT_PLAN.md`, `ARCHITECTURE_EXCELLENCE_PLAN.md`,
`ARCHITECTURE_REMEDIATION_PLAN_V2.md`, `FINAL_PRODUCTION_SUMMARY.md`, `PROJECT_COMPLETE.md`,
a 50 KB `TODO.md`, and a stray `docs/New Text Document.txt`.

Target structure:

```
README.md              # what it is, quickstart, links
ARCHITECTURE.md        # current design (authoritative)
CONTRIBUTING.md        # how to work on it
CHANGELOG.md           # what changed
docs/
  CONFIGURATION.md     # generated (WI-20)
  DEPLOYMENT.md        # runbook
  OPERATIONS.md        # backup/restore, incidents
  adr/                 # decision records — the permanent home for point-in-time analysis
  archive/             # superseded plans, dated, clearly marked
```

**Implementation tasks.**
1. Inventory and classify: current / superseded / delete.
2. Move superseded planning docs to `docs/archive/` with a dated header.
3. Convert durable decisions into ADRs (the `docs/adr/` convention already exists).
4. Consolidate `TODO.md` into the issue tracker.
5. Delete artifacts (`New Text Document.txt`, duplicate pricing HTML variants).
6. Add a docs index to `README.md`.
7. Fix `.gitignore` so `docs/` additions are not silently dropped (coordinated with WI-18).

**Refactoring.** None.

**Testing.** Link checker in CI.

**Acceptance criteria.**
- [ ] ≤6 markdown files at repo root.
- [ ] Every remaining doc is current or explicitly archived with a date.
- [ ] No broken internal links.
- [ ] A newcomer can identify the authoritative architecture document in one step.

**Rollback.** Git history preserves everything; low risk.

---

## 5. Risk & Mitigation Matrix

### 5.1 Implementation risks

| ID | Risk | Likelihood | Impact | Severity | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-01 | CI cannot be restored (account/billing outside team control) | Medium | **Critical** | 🔴 | Escalate to account owner day 1. Fallback: self-hosted runners or temporary alternate CI. Never proceed with unverified merges. | Eng lead |
| R-02 | Fixing the 98 `F821`s reveals deeper broken code paths | Medium | High | 🟠 | Triage before estimating. Timebox to 3 days; escalate scope changes rather than absorbing them. | Backend |
| R-03 | Auth migration (WI-11) breaks existing clients | Medium | High | 🟠 | Feature flag defaulting to legacy; one-version deprecation window; additive-only schema. | Backend |
| R-04 | History rewrite (WI-18) loses work or breaks clones | Low | **Critical** | 🔴 | Mandatory off-host mirror before rewriting. Scheduled window. All contributors notified and re-cloning. | Eng lead |
| R-05 | Schema migration (WI-17) corrupts production data | Low | **Critical** | 🔴 | Sequenced after WI-16 so a tested restore exists. Migrations verified against a real snapshot. Reversibility is an acceptance criterion. | Backend |
| R-06 | Playwright cannot run non-root (WI-13) | Medium | Medium | 🟡 | Isolate browser work into a separately-privileged service rather than relaxing the whole stack. | DevOps |
| R-07 | Rate limits break legitimate gateway traffic | Medium | Medium | 🟡 | Observe-only mode first (log, don't enforce); tune from real traffic; kill switch. | Backend |
| R-08 | Frontend does not build (unverified in assessment) | Medium | High | 🟠 | Verify before scoping WI-15. If broken, promote to P0 ahead of Phase 2. | Frontend |
| R-09 | Fixing 94 async-blocking sites regresses tool behavior | Medium | Medium | 🟡 | Per-module conversion with tests; ratcheted gate permits incremental progress. | Backend |
| R-10 | Coverage ratchet incentivizes low-value tests | Medium | Low | 🟢 | Pair the floor with review standards; mutation-test a sample of new tests. | Eng lead |

### 5.2 Architectural constraints

| Constraint | Implication | Handling |
|---|---|---|
| SQLite single writer | No horizontal scaling | D-1; document the ceiling or migrate |
| Import-linter contracts | New code must respect layer boundaries | Contracts run in CI; new ports for new capabilities |
| Domain purity | No I/O in `weebot/domain/` | Enforced; keep it that way |
| Ports as the extension seam | New adapters implement existing ports | WI-11 adds `ApiKeyPort` following the pattern |
| In-process scheduler | Multiple API replicas would duplicate jobs | Single API replica until D-1 = B, then leader election |
| Events as a JSON blob per session | O(n) reads; unbounded growth | `load_events=False` (WI-02); retention policy is follow-up work |

### 5.3 Backward compatibility

| Change | Breaking? | Strategy |
|---|---|---|
| WI-02 row contract | No | Internal; write path unchanged; existing rows load correctly |
| WI-03 port reduction | No | Reducing a port cannot break implementors |
| WI-05 `requires-python` | Yes, for 3.11 users | Already broken in practice (`numpy==2.5.1`); this makes the failure legible |
| WI-08 Compose split | Yes, for compose users | Documented in CHANGELOG; the prior config never served HTTP |
| WI-11 auth | **Yes** | Feature flag + deprecation window + legacy default |
| WI-12 rate limits | Potentially | Observe-only rollout; documented limits |
| WI-13 non-root | Yes, for volume permissions | Migration note on volume ownership |
| WI-17 schema | Potentially | Reversible migrations; backup first |
| WI-18 history | **Yes** | Re-clone required; coordinated |

### 5.4 Migration concerns

1. **Volume ownership (WI-13).** Existing `weebot_data` volumes are root-owned. Provide a
   one-time `chown` init container or documented manual step.
2. **API key migration (WI-11).** Issue equivalent per-principal keys before disabling the legacy
   path; do not force cutover in the same release that introduces the store.
3. **Schema snapshot (WI-17).** Capture a production schema dump *before* authoring migrations,
   so the baseline reflects reality rather than intent.
4. **Branch invalidation (WI-18).** All open branches must be merged or rebased before the
   rewrite. Sequenced last for exactly this reason.

---

## 6. Testing & Quality Assurance Strategy

### 6.1 Test pyramid — current vs target

| Level | Current | Target | Gap |
|---|---|---|---|
| Unit | 233 files | maintain | Coverage depth, not count |
| Integration | 12 files | ~20 | Failure paths, adapter contracts |
| Contract (port) | ~3 | 1 per critical port | `StateRepositoryPort`, `CheckpointPort`, `ApiKeyPort`, `LLMPort` |
| E2E | 3 files | ~6 | Full flow with mocked LLM (GAP-4) |
| Security | 2 files, 90 tests | +auth/rate-limit suites | Multi-principal isolation |
| Performance | 1 file | +latency benchmarks | p99 under concurrency |
| Frontend | **0** | smoke + 1 E2E | Everything |

### 6.2 Principles

- **Contract tests over per-adapter tests.** One suite parameterized across every implementation
  of a port. This is what would have caught WI-03's drift, and it is cheap given 63 ports.
- **Every fix ships with a regression test.** Non-negotiable for WI-02, WI-03, WI-04, WI-07 —
  each represents a defect that existing tests either caught and were not run, or did not cover.
- **Test the tests.** WI-08's smoke test must be shown to fail against a broken image. A gate
  that cannot fail is worse than no gate — it manufactures false confidence, which is precisely
  the failure mode this whole plan addresses.
- **Deterministic by default.** Network-dependent tests stay behind the existing `external`
  marker.

### 6.3 Quality gates (target CI pipeline)

| Gate | Command | Blocking | Phase |
|---|---|---|---|
| Architecture contracts | `lint-imports` | ✅ | exists |
| Undefined names | `ruff check --select F,E9` | ✅ | WI-07 |
| Full lint | `ruff check` | ⚠️ warn → block | post-cleanup |
| Env access | `make lint-env-access` | ✅ | WI-20 |
| Async I/O | `make lint-async-io` | ✅ ratcheted | WI-14 |
| Secret scan | `check-secrets.sh --ci` | ✅ | exists |
| Unit + integration | `pytest -m "not external"` | ✅ | WI-06 |
| Coverage | `--cov --cov-fail-under` | ✅ ratcheted | WI-21 |
| Dependency CVEs | `pip-audit`, `npm audit` | ✅ | WI-10 |
| SAST | `bandit` | ✅ | WI-10 |
| Container scan | Trivy | ✅ | WI-13 |
| Frontend | lint, tsc, build, test | ✅ | WI-15 |
| Docker smoke | compose up + probe | ✅ | WI-08 |
| Schema drift | migration check | ✅ | WI-17 |
| Config drift | generated-file check | ✅ | WI-20 |

### 6.4 Code review standards

- No self-merge on `main`; one approving review minimum.
- PRs under ~400 lines where practical — WI-07 explicitly excludes the 10k-line cosmetic cleanup
  for this reason.
- Every PR states its testing evidence.
- Security-relevant PRs (WI-11, WI-12, WI-13) require a second reviewer.
- Conventional Commits (already in use).

---

## 7. Deployment & Rollback Plan

### 7.1 Environments

| Env | Purpose | Data | Gate to promote |
|---|---|---|---|
| Local | Development | Disposable | Full suite green |
| CI | Verification | Ephemeral | All gates green |
| Staging | Pre-production | Anonymized copy | Smoke + manual E2E |
| Production | Live | Real | Staging soak ≥24h |

Staging does not exist today. Establishing it is a prerequisite for Phase 2 — WI-11 and WI-17
must not have production as their first real-data environment.

### 7.2 Deployment sequence per phase

**Phase 0.** No production deployment. Repository and CI changes only.

**Phase 1.** First real deployment. Order matters:
1. Build and scan image.
2. Deploy to staging; verify `/api/health`, `/api/ready`, `/api/live`.
3. Confirm structured logs and correlation IDs are flowing.
4. Soak 24h; watch error rate and p99 latency.
5. Promote.

**Phase 2.** Highest-risk phase. Deploy items independently, never batched:
1. WI-13 (containers) first — infrastructure-only, easiest rollback.
2. WI-12 (rate limiting) in observe-only mode; enforce after tuning against real traffic.
3. WI-16 (backup) before any schema work. Rehearse a restore.
4. WI-17 (schema) with a fresh backup taken immediately prior.
5. WI-11 (auth) last, flag-defaulted to legacy; flip per-environment after key issuance.

**Phase 3.** WI-18 requires a coordinated maintenance window.

### 7.3 Rollback procedures

| Scenario | Detection | Action | RTO |
|---|---|---|---|
| Bad image | Health probe fails | Redeploy previous tag | <5 min |
| Auth regression | 401/403 spike | `WEEBOT_AUTH_MODE=legacy` | <1 min |
| Rate limits too aggressive | 429 spike | `WEEBOT_RATE_LIMIT_ENABLED=false` | <1 min |
| Migration failure | Entrypoint exits non-zero | `alembic downgrade -1`; restore if needed | <30 min |
| Data corruption | Integrity check / user report | Restore from backup (WI-16) | Per rehearsed RTO |
| Container hardening breaks browser | Tool errors | Revert compose profile | <5 min |

**Principle:** every Phase 2 item ships behind a config-level kill switch. A rollback that
requires a rebuild is too slow for a security or availability regression.

### 7.4 Monitoring during rollout

Watch, per deploy: error rate (`weebot_exceptions_total`), p99 latency, LLM failure and
circuit-breaker state, DB pool utilization, rate-limit hits, backup freshness, auth failure rate.

Alert thresholds must be set *before* the deploy, not derived from the incident.

---

## 8. Post-Implementation Validation Checklist

### 8.1 Correctness

- [ ] `pytest tests/ -m "not external"` — 0 failures, 0 errors
- [ ] `ruff check weebot/ cli/ --select F,E9` — 0 findings
- [ ] `lint-imports` — 6/6 contracts kept
- [ ] `make check` — passes end to end
- [ ] Coverage ≥60% global, ≥90% domain
- [ ] `python scripts/lint_async_io.py` — 0 or ratcheted
- [ ] Session save → load → resume verified end to end
- [ ] `GoalAgent.decompose()` and `PlanActFlow._maybe_save_checkpoint()` execute under test
- [ ] Model catalog validator — 0 warnings

### 8.2 Deployment

- [ ] `pip install .` succeeds on a clean 3.12 environment
- [ ] `docker compose up -d --wait` yields a healthy stack
- [ ] `/api/health`, `/api/ready`, `/api/live` all respond correctly
- [ ] Healthcheck reports unhealthy when the server process is killed
- [ ] No container runs as root
- [ ] Resource limits enforced
- [ ] Migrations run at entrypoint; failure blocks startup
- [ ] CI smoke test demonstrably fails against a broken image

### 8.3 Security

- [ ] Two principals cannot access each other's sessions
- [ ] Expired and revoked keys rejected
- [ ] No plaintext credentials at rest or in logs
- [ ] Rate limits enforced; health endpoints exempt
- [ ] `pip-audit`, `bandit`, `npm audit`, Trivy — 0 high/critical, or documented with expiry
- [ ] `check-secrets.sh` clean
- [ ] Valkey requires auth and is not host-published
- [ ] `WEEBOT_ENABLE_UNSAFE_MIGRATION_SCRIPTS` documented and defaulted off
- [ ] Existing penetration suite still passes

### 8.4 Observability

- [ ] Web and MCP emit structured JSON logs
- [ ] Correlation ID on every response, traceable end to end
- [ ] Prometheus scrapes successfully under production auth settings
- [ ] Tracing spans emitted for flow execution
- [ ] Alerts configured for error rate, latency, breaker state, backup staleness

### 8.5 Operability

- [ ] Backup runs on schedule and is integrity-verified
- [ ] **A restore has been performed end to end from a real artifact**
- [ ] RPO and RTO documented as measured numbers
- [ ] Deployment runbook exists and has been followed by someone who did not write it
- [ ] Rollback rehearsed for at least one Phase 2 item

### 8.6 Governance

- [ ] `LICENSE` present and referenced in package metadata
- [ ] `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md` present
- [ ] 0 undocumented environment variables
- [ ] ≤6 markdown files at repo root; the rest current or dated-archived
- [ ] Clone size reduced >40 MB; no dependency directories tracked
- [ ] Personal-data decision documented
- [ ] `main` protected; CI required
- [ ] One authoritative version string

### 8.7 The meta-check

- [ ] **CI has been green on `main` for 14 consecutive days.**

This is the real exit criterion. Every other box can be ticked by a single heroic push; only this
one demonstrates that the process which failed in July is working again.

---

## Appendix A — Engineering Practices Applied

| Practice | Where it shows up in this plan |
|---|---|
| **Single Responsibility** | WI-03 splits checkpointing out of `StateRepositoryPort`; WI-08 splits API from MCP runtime |
| **Open/Closed** | WI-11 adds `ApiKeyPort` rather than modifying auth call sites |
| **Liskov Substitution** | WI-03 reconciles the `list_sessions` signature drift; contract tests enforce substitutability |
| **Interface Segregation** | WI-03 — the plan's central architectural fix |
| **Dependency Inversion** | Already enforced by import-linter; WI-11/WI-16 follow the pattern with new ports |
| **Clean Architecture** | All new code respects the four layers; contracts gate every PR |
| **Separation of Concerns** | WI-08 separates HTTP from MCP; WI-09 separates logging config from app logic |
| **DRY** | WI-03 deletes duplicated checkpoint methods; WI-07 centralizes LLM constants; WI-20 generates config docs from one source |
| **KISS** | WI-02 fixes the contract at one boundary rather than patching consumers |
| **YAGNI** | D-1 recommends staying on SQLite absent a real requirement; no k8s/mesh/event-sourcing proposed |
| **Secure by Design** | WI-11 hashes at rest; WI-12 fails closed; WI-13 least privilege; WI-10 shifts CVE detection left |
| **Defensive Programming** | WI-02 asserts input shape; WI-04 validates catalog at startup; WI-08 makes migration failure fatal |
| **Observability** | WI-09 (logs + correlation), WI-12 (rate metrics), WI-16 (backup metrics), WI-07 (restores tracing) |
| **CI/CD** | WI-01 restores it; WI-06/10/15/21 extend it; every gate must be provably able to fail |
| **Code review** | §6.4 — bounded PR size, mandatory testing evidence, two reviewers on security work |
| **Documentation** | WI-19, WI-20, WI-22; ADRs for durable decisions |
| **Performance** | WI-14 (event loop), WI-02 (`load_events=False`), latency benchmarks in §6.1 |
| **Scalability** | D-1 makes the ceiling an explicit decision rather than an accident |

---

## Appendix B — Effort Summary

| Phase | Items | Effort | Cumulative |
|---|---|---|---|
| 0 — Restore feedback loop | 6 | 3–5 days | ~1 week |
| 1 — Close correctness gaps | 4 | 7 days | ~2.5 weeks |
| 2 — Harden | 7 | 18 days | ~6 weeks |
| 3 — Professionalize | 5 | 7 days | ~7 weeks |

Single engineer, sequential. Phase 2's seven items are largely independent and compress to ~2
weeks with two engineers, bringing the total to roughly 4–5 weeks.

Estimates assume WI-01 resolves within 2 days. If Actions cannot be restored, the entire plan
stalls — which is the strongest argument for treating it as day-one work rather than a
housekeeping task.
