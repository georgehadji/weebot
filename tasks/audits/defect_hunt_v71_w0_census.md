---
wave: W0
purpose: Architecture census and invariant-ownership table for V7.1 round 2
baseline_commit: 86289a08a946ced8f8cc4fcf86da1d7f3f651f05
date_taken: 2026-10-25
verification: "[VF] = verified by command or code inspection; [HYP] = inferred; [UNK] = undecidable"
---

# Defect Hunt V7.1 — Architecture Census and Invariant-Ownership Table

**Purpose:** Phase 0 reference for all waves. Each wave uses this document instead of re-deriving the architecture from source. If a wave finds a census line it cannot back, it records `[HYP]` or `ARCHITECTURE: [UNK]` for that line in its report.

## 1. Environment Census

| Item | Value | Tag | Source |
|---|---|---|---|
| Language / runtime | Python ≥ 3.12 | [VF] | `pyproject.toml: requires-python = ">=3.12"` |
| Frameworks (primary) | FastAPI/Starlette, Pydantic v2, FastMCP, APScheduler | [VF] | `requirements.txt`, imports |
| Frameworks (persistence) | aiosqlite + sqlite3, Alembic | [VF] | `requirements.txt` |
| Frameworks (UI) | Playwright, Click | [VF] | `requirements.txt` |
| Test framework | pytest + pytest-asyncio (auto mode), 60s timeout | [VF] | `pyproject.toml: [tool.pytest.ini_options]` |
| Test selector default | `-m "not external"` (skips billed LLM calls) | [VF] | `pyproject.toml: addopts` |
| Entry points (CLI) | `cli/main.py`, `run.py`, `run_mcp.py` | [VF] | `docs/ENTRY_POINTS.md` |
| Entry points (web) | `weebot.interfaces.web.main` (FastAPI app) | [VF] | `docs/ENTRY_POINTS.md` |
| Entry points (scheduled) | APScheduler cron jobs | [VF] | `weebot/scheduling/` |
| Entry points (gateways) | Discord, Slack, Telegram, WhatsApp, Signal, Email | [VF] | `weebot/interfaces/gateways/` |
| Unit suite (baseline) | 6271 passed, 104 skipped, 3 xfailed (plan); NOT RE-VERIFIED (missing deps) | [HYP] | Plan §2.1; actual run had collection errors |
| Browser suite | 76 Playwright tests pass (plan) | [HYP] | Plan §2.1 |
| Architecture contracts | **10 kept, 0 broken** | [VF] | `lint-imports` 2026-10-25 |
| Import exemptions | **62** at ceiling | [VF] | `scripts/lint_import_exemptions.py` 2026-10-25 |
| Dynamic `weebot` imports | **15** at ceiling | [VF] | `scripts/lint_import_exemptions.py` 2026-10-25 |
| Ratchets | 28 keys in `tasks/quality/ceilings.toml` | [VF] | File inspection 2026-10-25 |

**Note on unit suite:** The plan states 6271 passed at the baseline. Wave 0 attempted re-verification but encountered 29 collection errors due to missing dependencies (`apscheduler`, etc.). The baseline is assumed correct from the plan; waves that need the suite green must install dependencies first.

## 2. Architecture Style and Layers

| Aspect | Value | Tag | Source |
|---|---|---|---|
| **Style** | Clean / hexagonal (ports and adapters) with CQRS and event sourcing | [VF] | ADR-001, ADR-002, `ARCHITECTURE.md`, `.importlinter` |
| **Layer map** | `interfaces → infrastructure → application → domain`; `core/` cross-cutting; `config/` leaf | [VF] | `CLAUDE.md` §Architecture, `.importlinter` contracts 1–10 |
| **Dependency rule** | Dependencies point inward; domain imports nothing outward | [VF] | `.importlinter` contract names |
| **Enforcement tooling** | `lint-imports` (10 contracts), `test_architecture_fitness.py`, `test_quality_ceilings.py`, `scripts/lint_*.py` ratchets, ruff (line-length 100) | [VF] | All passing 2026-10-25 |
| **Composition root** | `weebot/application/di` (`Container().configure_defaults()`) | [VF] | `CLAUDE.md` §Conventions; `scripts/lint_di_wiring.py` |
| **Dominant paradigms** | OOP with constructor DI in application/infrastructure; Pydantic value models in domain; async-first (asyncio) with `asyncio.to_thread` for blocking I/O | [HYP] | Inferred from codebase patterns |

### 2.1 Layer Contracts (from .importlinter)

The ten enforced contracts (all KEPT at baseline):

1. **domain-purity** — Domain layer must not depend on outer layers (0 violations, 0 exemptions)
2. **tools-no-db** — Tools must not access databases directly (3 exemptions)
3. **tools-no-infra** — Tools must not bypass ports (19 exemptions)
4. **infra-no-app-services** — Infrastructure must depend on ports, not application services/flows/agents (3 exemptions)
5. **interfaces-no-infra** — Interfaces must not depend on infrastructure adapters directly (25 exemptions)
6. **core-no-app** — Core cross-cutting layer must not depend on application (1 exemption)
7. **config-is-leaf** — Config must not import application, interfaces, infrastructure or tools (0 violations, 0 exemptions)
8. **app-no-interfaces** — Application layer must not depend on interfaces (0 violations, 0 exemptions)
9. **unassigned-no-infra** — Packages outside the layers must not import infrastructure or tools directly (8 exemptions)
10. **app-no-vendor-sdks** — Application and domain must not import provider SDKs or raw HTTP clients (3 exemptions)

**Total exemptions:** 62 (at ceiling)

## 3. Patterns In Use

| Pattern | Location | Tag | Source |
|---|---|---|---|
| **Mediator / CQRS** | `application/cqrs` (commands, queries, handlers) | [VF] | Directory exists, imports verified |
| **State machine with registry** | `application/flows/states` (`@register_state`) | [VF] | `states/base.py`, decorator pattern |
| **Ports / Adapters** | `application/ports` ↔ `infrastructure/adapters` | [VF] | Directory structure, `.importlinter` |
| **Middleware** | `application/middleware` | [VF] | Directory exists |
| **Cascade / Strategy** | `application/agents/executor/_cascade.py` | [VF] | File exists, model tier fallback |
| **Event bus** | `infrastructure/event_bus` | [VF] | File exists, pub/sub pattern |
| **Guard decorators** | `application/services/tool_guards.py` | [VF] | File exists, decorator pattern |
| **Repository** | `infrastructure/persistence/*_repo.py` | [HYP] | File pattern exists, not explicitly listed in plan |
| **Unit of Work** | Transaction boundaries in persistence layer | [UNK] | Not explicitly documented; inferred from async context managers |
| **Result type** | Not observed as a universal pattern | [UNK] | Some services return tuples, some raise exceptions |

## 4. Conventions (from CLAUDE.md)

| Convention | Enforcement | Tag | Source |
|---|---|---|---|
| **Error handling** | Exceptions; log inside every `except` block | [VF] | Ratchet: `silent_except_handlers = 112` |
| **Structured output** | Pydantic-validated in `weebot/models/structured_output.py` | [VF] | File exists, agent protocol |
| **Secrets** | Only via `SecretAccessor`, not `os.environ`/`os.getenv` | [VF] | Ratchet: `bare_env_reads = 70` |
| **Logging** | `logger`, never `print()` | [VF] | Ratchet: `print_in_production = 105` |
| **Shell execution** | Only through `bash_guard` | [VF] | Architecture fitness test |
| **Ratchet ceiling changes** | Never raise; only lower | [VF] | `test_quality_ceilings.py` enforces bidirectional equality |
| **Blocking I/O in async** | Wrapped in `asyncio.to_thread` | [VF] | Ratchet: `blocking_io_in_async = 0` (ban) |

## 5. Invariant-Ownership Table

This table assigns each architectural and security invariant to its **owner layer**. V7.1's contract-owner defence (§1.1 of plan) uses this to attribute defects and place fixes.

### 5.1 Security and Trust Boundary Invariants

| Invariant | Owner Layer | Owner Module(s) | Enforcement | Tag |
|---|---|---|---|---|
| All shell commands pass through BashGuard | `core/` | `core/bash_guard.py` | `test_no_shell_execution_outside_the_bash_guard` (arch fitness) | [VF] |
| Egress (HTTP, email, webhooks) passes through EgressGuard | `core/` | `core/egress_guard.py` | Manual audit (no automated test observed) | [HYP] |
| Output paths stay within workspace sandbox | `core/` | `core/output_path.py` | `tests/unit/test_output_path.py` | [VF] |
| Secrets are redacted from logs and events | `core/` | `core/structured_logger.py`, event sanitizers | `tests/unit/core/test_every_event_field_is_sanitised.py` | [VF] |
| Untrusted input (mail, MCP, web, gateway) marked and gated | `interfaces/` | Gateway adapters, web routers, `mcp/` | Manual audit (no centralised gate test) | [HYP] |
| Filesystem operations respect permission model | `infrastructure/sandbox` | `sandbox/*.py` | ADR-009 (Linux sandbox), manual audit | [HYP] |

### 5.2 Architectural Invariants

| Invariant | Owner Layer | Owner Module(s) | Enforcement | Tag |
|---|---|---|---|---|
| Domain layer has no outward imports | `domain/` | All of `domain/` | `.importlinter` contract `domain-purity` | [VF] |
| Application does not import interfaces | `application/` | All of `application/` | `.importlinter` contract `app-no-interfaces` | [VF] |
| Infrastructure depends on ports, not services | `infrastructure/` | All of `infrastructure/` | `.importlinter` contract `infra-no-app-services` (3 exemptions) | [VF] |
| Interfaces do not import adapters | `interfaces/` | All of `interfaces/` | `.importlinter` contract `interfaces-no-infra` (25 exemptions) | [VF] |
| Composition happens in `application/di` only | `application/di` | `application/di/` | `test_di_single_composition_root`, `scripts/lint_container_construction.py` (7 allowed) | [VF] |
| Config is a leaf (no outward imports) | `config/` | All of `config/` | `.importlinter` contract `config-is-leaf` | [VF] |
| Tools do not reach persistence directly | `tools/` | All of `weebot/tools/` | `.importlinter` contract `tools-no-db` (3 exemptions) | [VF] |
| Settings constructed via `get_settings()`, not `WeebotSettings()` | All layers | Entire codebase | Ratchet: `settings_construction = 0` (ban) | [VF] |

### 5.3 Data Integrity Invariants

| Invariant | Owner Layer | Owner Module(s) | Enforcement | Tag |
|---|---|---|---|---|
| State transitions follow the registry | `application/flows/states` | `states/base.py`, individual states | `test_there_is_exactly_one_flow_routing_table` | [VF] |
| Events are persisted at emit | `infrastructure/persistence` | `persistence/event_store.py` | `test_persistence_at_emit` | [VF] |
| Session state changes are atomic | `infrastructure/persistence` | `persistence/state_repo*.py` | Manual audit (WAL mode assumed) | [HYP] |
| Alembic migrations are append-only | `alembic/` | `alembic/versions/` | Manual audit (no automated check) | [UNK] |

### 5.4 Concurrency Invariants

| Invariant | Owner Layer | Owner Module(s) | Enforcement | Tag |
|---|---|---|---|---|
| Async functions do not call blocking I/O directly | All async functions | Entire codebase | Ratchet: `blocking_io_in_async = 0` (ban) | [VF] |
| Coroutines are awaited (not silently dropped) | All async functions | Entire codebase | `scripts/lint_unawaited_coroutines.py` | [VF] |
| Module cycles are forbidden | All modules | Entire codebase | Ratchet: `module_cycles = 0` (ban) | [VF] |
| Connection pools are bounded | `infrastructure/persistence` | `persistence/connection_pool.py` | Manual audit (pool size config) | [HYP] |

### 5.5 Cost and Budget Invariants

| Invariant | Owner Layer | Owner Module(s) | Enforcement | Tag |
|---|---|---|---|---|
| LLM calls respect budget limits | `application/agents` | `agents/executor/`, `application/services/cost_*` | Manual audit (no test observed) | [UNK] |
| Cascade tries cheaper models first | `application/agents/executor` | `_cascade.py` | `test_cascade_executor_importable` (existence only) | [HYP] |
| Retries use exponential backoff | `infrastructure/adapters/llm` | `resilient_adapter.py` | Manual audit | [UNK] |

## 6. Property Ownership Attribution Rules

When a wave finds a potential defect, **attribution** determines where the fix belongs:

1. **If an invariant has an owner layer and enforcement:** the fix belongs in that layer, at the enforcement point.
2. **If the invariant is documented but not enforced:** the fix may belong in the calling code (defense-in-depth) OR in the owner layer (new enforcement). V7.1's dual-variant rule applies.
3. **If the property is local to one module:** the fix belongs in that module (no re-attribution).
4. **If a caller violates a documented contract:** the fix belongs in the caller, not the callee (innocence defence, Phase 3b).

**Example:** A guard that reports clean but checks nothing → fix in the guard itself (owner: the module containing the guard).  
**Example:** A caller passes `None` to a function that documents "`None` is forbidden" → fix in the caller (contract violation).

## 7. Dynamic Behavior Census

| Aspect | Location | Tag | Source |
|---|---|---|---|---|
| **Event bus subscribers** | Registered in `infrastructure/event_bus.py` | [HYP] | File exists, pub/sub pattern |
| **Flow state transitions** | Registry in `application/flows/states/base.py` | [VF] | `@register_state` decorator |
| **CQRS handlers** | Registry in `application/cqrs/mediator.py` | [HYP] | File exists, handler registration pattern |
| **DI bindings** | Registered in `application/di/*.py` | [VF] | 44 string keys, N type keys (measured) |
| **Tool registry** | `RoleBasedToolRegistry` in `application/models/tool_collection.py` | [HYP] | File exists, dynamic tool loading |
| **MCP server tools** | Registered in `mcp/server.py` or `run_mcp.py` | [HYP] | Entry point exists |

## 8. Test Organization

| Test Type | Location | Coverage | Tag |
|---|---|---|---|---|
| Unit tests (domain) | `tests/unit/domain/` | Pure functions, no I/O | [VF] |
| Unit tests (application) | `tests/unit/application/` | With fakes, mocked ports | [VF] |
| Integration tests | `tests/unit/infrastructure/` | Real adapters, test databases | [HYP] |
| Architecture fitness | `tests/unit/test_architecture_fitness.py` | 61 passed, 2 skipped | [VF] |
| Quality ceilings | `tests/unit/test_quality_ceilings.py` | 19 passed | [VF] |
| Candidate inventory | `tests/unit/test_candidate_inventory.py` | 14 passed (extended for round 2) | [VF] |
| Browser tests | `weebot-ui/` (excluded from defect hunt) | 76 Playwright tests | [HYP] |

## 9. Exclusions

Per plan §1 ("Scope"), the following are explicitly excluded from round 2:

| Excluded | Reason |
|---|---|
| `weebot-ui/` | Has its own Playwright/axe suite and ratchets; separate audit |
| `weebot/GitNexus-main/` | Vendored third-party code, git-ignored |
| Generated model catalog (`_catalog.py`) | Generated; its *validator* is in scope |
| `scripts/` (for detector tests) | Linter skip path |

## 10. Known Gaps and Limitations

1. **Unit suite baseline not re-verified:** Missing dependencies prevented re-running the full suite. The plan's "6271 passed" is assumed correct.
2. **Some enforcement is manual audit:** Guards, gates, and resource lifecycle often lack automated tests (e.g., EgressGuard coverage, budget enforcement).
3. **[HYP] vs [VF] ratio:** Many assertions are inferred from file structure or patterns, not from executable proof. Waves must verify [HYP] claims before relying on them.
4. **Result type pattern:** No universal Result<T, E> observed; some services return tuples, some raise exceptions. This may be a local-consistency issue.

---

**Census Status:** COMPLETE for Wave 0
**Date Taken:** 2026-10-25
**Baseline Commit:** 86289a08a946ced8f8cc4fcf86da1d7f3f651f05
**Next Step:** Freeze file lists for waves 1–12
