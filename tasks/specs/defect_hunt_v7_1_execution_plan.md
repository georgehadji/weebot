---
status: draft
date: 2026-10-25
---

# Autonomous Defect-Hunt (V7.1) — Whole-Backend Execution Plan, Round 2

**Created:** 2026-10-25 · **Branch at drafting:** `main` @ `86289a08`
**Protocol:** `AUTONOMOUS DEFECT-HUNT PROTOCOL — V7.1 (PROACTIVE, ARCHITECTURE-AWARE)` (EGFV · RAR · MRADO · PCST)
**Scope:** `weebot/` and `cli/` (Python 3.12), plus `alembic/`. `weebot-ui/` is excluded (it has its own
Playwright/axe suite and ratchets); `weebot/GitNexus-main/` is excluded (vendored, git-ignored).
**Predecessor:** [`defect_hunt_v7_execution_plan.md`](defect_hunt_v7_execution_plan.md) (round 1, September 2026,
reports in `tasks/audits/defect_hunt_*.md`, inventory in `tasks/audits/candidates.yml`).

Evidence tags are the protocol's own: **[VF]** verified (observed in this checkout or demonstrated by an executed
command), **[HYP]** hypothesis, **[UNK]** undecidable without runtime, **[FALSE]** contradicted. Every **[VF]** in
§2–§4 below was produced by a command run on 2026-10-25; the commands are in Appendix A.

---

## 1. What this plan is, and why it exists

The V7.1 prompt is a **single-target** loop (Phase 0 → Phase 8). It cannot be run once over the whole backend: Phase 0
exists precisely to *bound* the hunt, and a pass over ~135,000 lines would never reach Phase 8 or produce a defensible
coverage statement. This plan therefore does three things the prompt cannot do for itself:

1. **Runs Phase 0 once, globally** (Wave 0): environment, architecture census, invariant-ownership table, baseline.
2. **Decomposes the backend into twelve bounded hunt units** ("waves"), each running the full Phase 0-Wave → Phase 8
   loop with its own budget, counters and coverage statement.
3. **Specifies how each wave is launched, gated, merged and recorded**, so the programme can stop after any wave and
   still leave an honest result (Phase 8 allows PARTIAL).

### 1.1 What V7.1 adds over V7, and what that changes in the plan

| V7.1 addition | Consequence for execution |
|---|---|
| Architecture census (Phase 0), each line tagged [VF]/[HYP] with its source | A dedicated **Wave 0** deliverable. Weebot has real enforcement tooling, so most lines can be [VF]. |
| `Invariant owner` (Phase 1) and `Property owner` (Phase 2) | Candidates are attributed to a layer. A defect that fires only when a caller's documented contract is broken is **re-attributed**, not fixed in place. |
| Contract-owner innocence defence (Phase 3b) | The innocence attempt must cite the *enforcing code* in the owner layer. Waves that audit a lower layer need the layer above readable. |
| Fix placement (5a), mechanism ladder (5b), conformance gate (5c) | Every fix names its layer and mechanism and runs the enforcement tools (§6). New patterns need the recurrence test (≥2 instances), which only a programme-wide view can establish. |
| Two new self-review vectors (architectural conformance, paradigm consistency), eight in total | Self-review is wider; Phase 7 must turn the HOLDS [HYP] cases into tests. |
| `OBSERVATION` class (structural smell without a property violation) | A separate log (§8). Observations never enter the defect inventory or the counts. |
| Three independent counters (`hunt_iterations`, `fix_revisions`, `budget_spent`) | Recorded per wave in the report header. |

### 1.2 Why a second round is worth running

- **The code moved.** **[VF]** 317 commits touched `weebot/` and `cli/` since the September hunt (2026-09-05), covering
  roughly 250 distinct Python files (§4.1). A September clean-claim says nothing about them.
- **Round 1 was bounded by what it chose to look at.** **[VF]** Its 100 recorded candidates cluster in
  `application/flows` (23 references), `application/services` (12), `infrastructure/persistence` (9),
  `infrastructure/adapters` (6), `application/agents` (6) and `interfaces/web` (5). `application/services` is the
  largest package in the backend (22,704 lines in 118 files) and drew 12 references. Large regions —
  `application/cqrs`, `application/di`, `application/ports`, `domain/`, `config/`, `templates/`, `scheduling/`,
  `qmd_integration/`, most of `tools/` — have **no** or almost no candidates. Absence from the inventory is not a
  clean-claim; it is [UNK].
- **New code with no hunt at all:** local-model routing (Ollama), per-role model overrides and their web routes,
  session-lesson persistence and the misalignment-journal wiring, the title/presence pipeline, `count_events`, the
  `/run` MCP wait, and the UI-driven endpoints. Several of these were written in the last week.
- **The method improved.** V7.1's owner-layer placement would have re-homed fixes that round 1 patched in place.
  Round 2 re-examines round-1 fixes under the conformance gate as part of Wave 12.

---

## 2. PHASE 0-GLOBAL: environment, architecture and scope census (to be confirmed in Wave 0)

### 2.1 Static census

| Item | Value | Tag / source |
|---|---|---|
| Language / runtime | Python ≥ 3.12 (`pyproject.toml`); the repo venv is `.venv` | [VF] `requires-python = ">=3.12"` |
| Frameworks | FastAPI/Starlette, Pydantic v2, FastMCP, APScheduler, aiosqlite + sqlite3, Alembic, Click, Playwright | [VF] `requirements.txt`, imports |
| Test framework | pytest + pytest-asyncio (auto mode), 60 s timeout; `-m "not external"` by default | [VF] `pyproject.toml` |
| Entry points | `cli/main.py`, `run.py`, `run_mcp.py`, `weebot.interfaces.web.main`, scheduler (cron), gateways (Discord, Slack, Telegram, WhatsApp, Signal, Email) | [VF] `docs/ENTRY_POINTS.md` |
| Unit-suite baseline | **6271 passed, 104 skipped, 3 xfailed** on `main` @ `86289a08` | [VF] run 2026-10-25 |
| Browser suite | 76 Playwright tests pass | [VF] same day |
| Layer contracts | **10 kept, 0 broken** (`lint-imports`) | [VF] run 2026-10-25 |
| Import exemptions | **62**, at their ceiling (`scripts/lint_import_exemptions.py`) | [VF] |
| Dynamic `weebot` imports | 15, at ceiling | [VF] |
| Ratchets | 28 keys in `tasks/quality/ceilings.toml`, exact-equality both ways; `tests/unit/test_quality_ceilings.py` pins the key set | [VF] |

Two numbers from September no longer hold and are **not** reused: the "7 contracts" and the "67 `ignore_imports`".

### 2.2 Architecture census

| Line | Value | Tag and source |
|---|---|---|
| **Style** | Clean / hexagonal (ports and adapters) with CQRS and event sourcing | [VF] ADR 001, ADR 002, `ARCHITECTURE.md`, `.importlinter` |
| **Layer map** | `interfaces → infrastructure → application → domain`; `core/` cross-cutting; `config/` leaf | [VF] `CLAUDE.md` §Architecture, `.importlinter` contracts 1–10 |
| **Dependency rule** | Domain imports nothing outward; application must not import interfaces; infrastructure depends on application *ports* only; interfaces must not import infrastructure adapters directly; tools must not reach persistence or adapters; config imports no other layer; application and domain import no provider SDK or raw HTTP client | [VF] the ten contract names in `.importlinter` |
| **Enforcement tooling** | `lint-imports` (10 contracts), `tests/unit/test_architecture_fitness.py`, `tests/unit/test_quality_ceilings.py`, `scripts/lint_*.py` ratchets, ruff (line length 100) | [VF] present and passing today |
| **Composition root** | `weebot/application/di` (`Container().configure_defaults()`) is the one place allowed to know concretes | [VF] `CLAUDE.md` §Conventions; DI-wiring lint `scripts/lint_di_wiring.py` |
| **Dominant paradigms** | OOP with constructor DI in application/infrastructure; Pydantic value models in domain; async-first (asyncio) with `asyncio.to_thread` for blocking I/O; a few pure-function services in `domain/services` | [HYP] inferred; Wave 0 confirms per package |
| **Patterns in use** (one location each) | Mediator/CQRS `application/cqrs`; state machine with registry `application/flows/states` (`@register_state`); ports/adapters `application/ports` ↔ `infrastructure/adapters`; middleware `application/middleware`; cascade/strategy `application/agents/executor/_cascade.py`; event bus `infrastructure/event_bus`; guard decorators `application/services/tool_guards.py` | [VF] for the locations named; Wave 0 adds repository/unit-of-work/Result-type locations **only if it can point to them** |
| **Conventions** | Errors: exceptions, with a log inside every `except`; structured agent output validated by Pydantic (`weebot/models/structured_output.py`); secrets only via `SecretAccessor`; `logger`, never `print`; shell only through `bash_guard`; never raise a ratchet ceiling | [VF] `CLAUDE.md` §Design Patterns and Conventions; ratchets |
| **Invariant ownership** | To be built in Wave 0 as `tasks/audits/defect_hunt_v71_w0_census.md`, one row per invariant, seeded from ADRs 001–015, `docs/SECURITY_MODEL.md`, `map/objects/*` cards and `.importlinter` | [UNK] until written |

If Wave 0 finds a census line it cannot back, it records `[HYP]` or `ARCHITECTURE: [UNK]` for that line; the
local-consistency rule then applies to fixes in that package. That is not blocking.

### 2.3 Threat model (ranked by cost if real)

| Rank | Threat | Where it lives |
|---|---|---|
| T1 | A guard or gate that fails open (reports clean, checks nothing); command, path or egress escape | `core/`, `infrastructure/security`, `infrastructure/sandbox`, `application/services/tool_guards.py` |
| T2 | Untrusted input reaching action: inbound mail, MCP output, web pages, gateway messages, webhook bodies | `interfaces/`, `mcp/`, `tools/`, trust boundary |
| T3 | Silent wrong result or lost data: partial writes, swallowed errors, event/state divergence, migration damage | `infrastructure/persistence`, `cqrs`, `flows`, `alembic` |
| T4 | Runaway or mis-attributed spend: cascade loops, retries without backoff, budget bypass, billing errors treated as retryable | `agents/executor`, `adapters/llm`, cost services |
| T5 | Liveness: stuck RUNNING sessions, loops that never terminate, resource leaks, deadlock | `flows`, `task_runner`, `background_tasks`, browser/sandbox |
| T6 | Concurrency: shared mutable state, check-then-act, await-holding-lock | `flows`, `connection_pool`, event bus, caches |
| T7 | Architecture erosion that produces a property violation (a bypassed port, state written around the owner) | everywhere; hunted as the `Architecture-conformance` class |

### 2.4 Defect taxonomy, instantiated

The V7.1 catalogue, with the identifiers used in round 1 so inventories stay comparable:

| ID | Class |
|---|---|
| C1 | Boundary and arithmetic |
| C2 | Fail-open control (a gate that checks nothing) — the dominant class in round 1; not detectable by any linter |
| C3 | Trust-boundary and input |
| C4 | Type and serialization |
| C5 | Resource lifecycle |
| C6 | Concurrency |
| C7 | Error and exception paths |
| C8 | Contract / dependency assumptions |
| C9 | State machine |
| C10 | **Architecture-conformance** (new): a boundary crossing or abstraction bypass that violates a *property*. A smell without a violation is an OBSERVATION. |

### 2.5 Baseline rule

A wave does not start against a red baseline. Before each wave: unit suite green, `lint-imports` 10/10, every ratchet at
its ceiling, `git status` clean on the wave branch. A red baseline halts the wave and is reported, never worked around.

---

## 3. Approach

Round 1 evaluated three organisations (risk-ranked subsystem waves, taxonomy-horizontal sweeps, signal-first).
The conclusions stand and are reused: **subsystem waves as the engine, instruments first, class sweeps inside each
wave, an explicit seam wave at the end.** Taxonomy-horizontal sweeps remain rejected because their pull requests touch
the whole tree and defeat the ≤ 15-line / ≤ 1-function constraint at aggregate scale.

One change for round 2: **waves follow layers as well as risk.** V7.1's contract-owner defence needs the owning layer's
code in view. Waves are therefore grouped by layer (§5) and ordered so that an owner layer is audited before, or in the
same group as, the layers that rely on it.

---

## 4. Round 2 surface

### 4.1 Size and recent change **[VF]**

"Lines" are physical lines of `.py` files; "files touched" counts distinct files changed since 2026-09-05. A "≤1"
means the package did not appear above the one-file cut-off of the listing used.

| Package | Lines | Files touched since Sep | Notes |
|---|---:|---:|---|
| `application/services` | 22,704 | 56 | largest; 118 files |
| `infrastructure/adapters` | 9,245 | 23 | LLM, local routing, mail, etc. |
| `application/flows` | 8,301 | 35 | state machine |
| `infrastructure/persistence` | 5,973 | 13 | SQLite, pools, stores |
| `application/agents` | 5,607 | 15 | planner, executor, cascade |
| `interfaces/web` | 4,530 | 18 | routers, ws, auth |
| `application/ports` | 4,286 | 14 | |
| `application/cqrs` | 3,125 | 10 | |
| `infrastructure/security` | 2,918 | 6 | |
| `infrastructure/sandbox` | 2,393 | 5 | |
| `application/di` | 2,034 | 8 | composition root |
| `tools` | 12,573 | ≤1 | 52 files; round 1 saw only a few |
| `core` | 11,864 | ≤1 | guards, trust boundary |
| `config` | 10,853 | ≤1 | ≈5.8k lines are the generated catalog |
| `domain` | 8,284 | 21 | models + services |
| `templates` | 7,357 | ≤1 | never hunted |
| `cli` | 4,790 | n/a | 19 files |
| `qmd_integration`, `scheduling`, `mcp`, `osworld`, `agents`, `utils`, `models` | ≈6,200 combined | ≤1 | thin or never hunted |

### 4.2 Round 1 carry-over **[VF]**

- `tasks/audits/candidates.yml` holds 100 records: **87 fixed, 13 cleared, none open**. A test
  (`tests/unit/test_candidate_inventory.py`) enforces that a cleared or deferred record carries a `verdict_note`.
  Round 2 **reuses this file**: new records carry `round: 2` and ids `H<wave>.<n>` (for example `H5.3`), so they cannot
  collide with `D<n>`. The inventory test needs a small extension to accept the `round` field; that edit is part of
  Wave 0.
- Cleared candidates are not regenerated (Phase 2 rule). Wave 0 builds a **cleared-register** from the 13 cleared
  records so each wave's Phase 2 can exclude them by id and location.
- Innocence defences recorded in round 1 can be invalidated by later change (V7 §5). Wave 12 re-verifies the 13.

---

## 5. The wave plan

Groups run in order A → D. Waves inside a group touch disjoint files and may run in parallel sessions (§7.3); the
group-end gate (§7.5) merges them one at a time.

| Wave | Group | Surface | Lines | Classes hunted | Threats | Budget (candidates) |
|---|---|---|---:|---|---|---:|
| **W0** | — | Instruments, baseline, census, cleared-register | — | repair, not hunt | precondition | n/a |
| **W1** | A | Security and trust boundary | ≈17k | C2 C3 C7 C10 | T1 T2 | 30 |
| **W2** | A | Interfaces and non-human entry points | ≈16k | C3 C2 C7 C9 | T2 T5 | 30 |
| **W3** | B | Flow engine and state machine | ≈10k | C9 C6 C7 C5 | T3 T5 T6 | 30 |
| **W4** | B | CQRS, DI, ports and event plumbing | ≈10k | C10 C4 C8 C7 | T3 T7 | 25 |
| **W5** | B | Application services I: execution, verification, gates, cost | ≈11k | C2 C7 C8 C1 | T1 T3 T4 | 30 |
| **W6** | B | Application services II: learning, memory, skills, harness, retrieval | ≈12k | C4 C7 C5 C6 | T3 T5 | 25 |
| **W7** | C | LLM-facing: agents, cascade, adapters, local routing, model tables | ≈15k | C8 C7 C1 C6 | T4 | 30 |
| **W8** | C | Persistence and data integrity | ≈8k | C7 C6 C5 C4 | T3 T6 | 25 |
| **W9** | C | Tools and resource lifecycle | ≈17k | C5 C3 C7 C2 | T1 T2 T5 | 30 |
| **W10** | D | Domain and configuration | ≈17k | C10 C4 C1 C2 | T3 T7 | 20 |
| **W11** | D | Periphery: templates, qmd, scheduling, osworld, agents/, utils, observability, harness, eval | ≈15k | C5 C7 C3 | T5 | 15 |
| **W12** | — | Seams, fix-interaction, architecture-conformance sweep, programme statement | cross-cutting | all | all | 20 |

### 5.1 Definitions

**W0 — Instruments, baseline, census.** Precondition, not a hunt.
- Re-take the baseline of §2.1 at the wave branch point; record any gate that is red or unreliable.
- Re-test the detectors the hunt will lean on (`lint_async_io`, `lint_except_pass`, `lint_import_exemptions`,
  `lint_unawaited_coroutines`, `lint_module_cycles`) against known positives and negatives. A detector that reports clean
  while checking nothing was round 1's most important finding; do not assume it stayed fixed.
- Write the architecture census and invariant-ownership table (`tasks/audits/defect_hunt_v71_w0_census.md`),
  each row tagged and sourced. Seed from ADRs 001–015, `docs/SECURITY_MODEL.md`, `map/objects/**` and `.importlinter`.
- Freeze the file lists of every wave (§5.2), and the **services split** between W5 and W6.
- Build the cleared-register and extend `test_candidate_inventory.py` for `round`.
- Produce a **last-audited manifest**: per package, the commit round 1 audited and the files changed since.

**W1 — Security and trust boundary.** `core/` (bash guard, egress guard, trust boundary, output path, redaction,
credential sanitizer, gateway auth, behavior tracker), `infrastructure/security`, `infrastructure/sandbox`,
`application/services/tool_guards.py`, `fs_permission_*`. Focus: fail-open gates, path and command escapes,
redaction coverage, approval-gate bypass. Seeds: the round-1 cleared guards (re-verify, do not regenerate).

**W2 — Interfaces and non-human entry.** `interfaces/web` (routers including the new `/models/roles` and `/run`,
websocket handlers, auth middleware), `interfaces/gateways`, `interfaces/cli`, `cli/`, `mcp/` server, `scheduling/`
(cron), webhook. Focus: unauthenticated paths, mutation without `require_mutation_identity`, input size and format,
ownership checks, gateway allow-list default, stuck RUNNING sessions after restart (observed live; see §10).

**W3 — Flow engine.** `application/flows` (states, `PlanActFlow`, collaborators), `termination`, `middleware`,
`application/models`, `strategies`. Focus: illegal transitions, loops without exit (round 2 already found one in
`PlanningState`), status overwritten by the runner, cancellation and resume races.

**W4 — CQRS, DI, ports.** `cqrs` (mediator, handlers, queries), `di`, `application/ports`, `infrastructure/events`,
`event_bus`. Focus: handler contracts, query result shapes (a missing key crashed the UI), registry wiring, port
signatures versus adapter behaviour, composition-root leaks.

**W5 — Application services I (execution path).** Verification (`chain_of_verification`, `step_evidence_auditor`,
`code_reviewer_service`, `idea_gate`, `intent_review_service`, `main_review_service`), `task_runner`, `effect_ledger`,
cost and budget meters, `audit_service`, `context_manager` and compressors, `background_tasks`, gateway command
dispatch. Final file list frozen in W0.

**W6 — Application services II (learning and memory).** `autonomous_learning`, `behavioral_learner`,
`correction_tracker`, `meta_critic`, skill retrievers, `materializing_skill_store`, `memory_*`, `knowledge_graph`,
`self_improver`, `evolution_tracker`, harness resolvers and scorers, `opportunity_engine`, research services, MCP tool
retrieval. Includes the new session-lesson persistence and misalignment-journal wiring.

**W7 — LLM-facing.** `application/agents` (planner, executor, cascade, hyper-agent), `infrastructure/adapters/llm`
and local routing (Ollama), `config/model_refs`, role overrides, catalog validator, `application/services/model_registry`,
`routing`, `role_model_selector`. Focus: retry classes (billing errors treated as retryable), cascade termination,
hedging, cost attribution, override precedence, catalog drift. Generated `_catalog.py` is excluded; its *validator* is in.

**W8 — Persistence.** `infrastructure/persistence` (connection pool, stores, event store, summary repo), `cache`,
`queue`, `alembic/`. Focus: transaction boundaries, partial writes, WAL and pool lifecycle, migration safety, backup and
restore. Alembic history changes are always `[REQUIRES HUMAN REVIEW]`.

**W9 — Tools and resource lifecycle.** `weebot/tools` (52 files), `infrastructure/browser`, `mcp`, `document`,
`monitors`, `notifications`. Focus: file handles, subprocess and browser lifetime, timeouts, tool output trust labels,
every shell call routed through `bash_guard`.

**W10 — Domain and configuration.** `domain` (models and services purity: no I/O), `config` (settings, feature flags,
model tables; not the generated catalog), `models/structured_output`, `utils`. Focus: purity violations that cause
a property failure, settings defaults that fail open, flag combinations, serialization drift.

**W11 — Periphery.** `templates` (7.4k lines, never hunted), `qmd_integration`, `osworld`, `weebot/agents`,
`observability`, `scoring`, `application/skills`, `harness`, `eval`, `document`. Lowest threat rank; small budget. If
reachability analysis shows a region is `DEAD`, it is recorded as a low-severity finding, not skipped.

**W12 — Seams and programme close.** Cross-wave fix-interaction (round 1's W8 found a regression that passed every
wave's tests); a **re-sweep of every file changed by W1–W11 against all ten classes**, which round 1 explicitly did not do;
the architecture-conformance sweep (C10) over module boundaries; re-verification of the 13 round-1 cleared defences; the
programme-level coverage statement.

### 5.2 Where the wave surface is set

Each wave's exact file list is frozen at the end of W0 from `git ls-files` and written into that wave's report header.
Wave surfaces must be a **partition**: a file belongs to exactly one wave, so no two waves' fixes can touch the same line
unnoticed. W0 fails if the union misses a tracked `.py` file or two waves overlap.

---

## 6. Per-fix architecture invariants (replaces V7 §6)

The protocol's conformance gate (5c) becomes these checkable conditions.

1. **`lint-imports` stays 10 / 10 KEPT after every fix**, run per fix, not per wave.
2. **No new `ignore_imports` entry** and no raised ceiling in `tasks/quality/ceilings.toml`, ever. Needing either makes
   the fix `[REQUIRES HUMAN REVIEW: cross-boundary mechanism]`. Ceilings may only be lowered.
3. **Dependency direction holds**; `domain` stays pure. A domain fix that needs an outward import is the wrong fix.
4. **Fix through ports, not around them.** A fix that reaches past a port to an adapter is symptomatic by construction.
5. **`application/di` is the composition root.** Wiring fixes belong there.
6. **A port signature change is automatically `[REQUIRES HUMAN REVIEW]`**, as is any change to an Alembic revision, and
   any change that widens what a security guard permits.
7. **Structured output stays Pydantic-validated.** Do not widen a model to `Any` to make a parse pass.
8. **Shell goes through `bash_guard`.** A new subprocess site routes through it or is justified in the wave report.
9. **Logging and errors:** log inside every `except`; narrow the exception; use `SecretAccessor`, not `os.environ`.
10. **Tests ship with the fix**, in the same commit, in the project's style and tier (§7.6).
11. **Map cards stay true.** `map/` cards cite `path:line`; if a fix moves a cited line, update the card in the same
    commit (`test_map_is_consistent`). Fifty citations already drift in `_factories.py`, `settings.py` and
    `adapter_factory.py`; fixing those is outside the hunt but the hunt must not add to them.

### 6.1 Enforcement commands (run on the changed code; the output is the [VF] for vector 7)

```bash
.venv/Scripts/lint-imports.exe
.venv/Scripts/python.exe -m pytest tests/unit/test_architecture_fitness.py tests/unit/test_quality_ceilings.py -q
.venv/Scripts/python.exe scripts/lint_except_pass.py
.venv/Scripts/python.exe scripts/lint_async_io.py
.venv/Scripts/python.exe scripts/lint_import_exemptions.py
.venv/Scripts/python.exe scripts/lint_di_wiring.py
.venv/Scripts/python.exe -m ruff check <changed files>
```

`make` is not installed in this environment; run the scripts directly. `make check` remains the CI-equivalent gate
when `make` is available.

### 6.2 Fix policy

- The ≤ 15 lines / ≤ 1 function limit is the default. In `application/services`, `flows` and `agents` it will often
  force the dual-variant rule; record each as `[CONSTRAINT-FORCED ESCALATION]` so a reviewer can tell policy artefacts
  from risky fixes.
- Symptomatic fixes are rejected: adding a log line to a fail-open gate is not a fix, the gate must change what it
  *returns*. Round 2 found this shape again (a rejected plan left the session RUNNING; a log line alone would not have
  stopped the loop).
- Defence-in-depth guards are allowed only with the owner fix present or escalated in the same output.

---

## 7. Running a wave

### 7.1 The launch wrapper

Each wave is one run of the V7.1 prompt, **prefixed by the wave parameter block** below. The prompt text itself is not
edited; the block supplies Phase 0's scope and budget so the wave does not redo the census.

```
WAVE PARAMETERS — V7.1 round 2
Wave:            W<N> — <surface name>
Phase 0:         Use tasks/audits/defect_hunt_v71_w0_census.md as the architecture census and environment
                 census. Do not re-derive it. Mark any line you find to be wrong and stop to report it.
In-scope:        <frozen file list from W0>
Out-of-scope:    every other package; weebot-ui/; weebot/GitNexus-main/; generated model catalog
Audit budget:    <N> candidate defects; hunt_iterations cap 3 per region tier; fix_revisions cap 1
Classes:         <C-ids for this wave>        Threats: <T-ids>
Threat model:    tasks/specs/defect_hunt_v7_1_execution_plan.md §2.3
Do not regenerate: ids and locations in the cleared-register (tasks/audits/defect_hunt_v71_cleared_register.md)
Seeds (HYP):     <wave seeds; Phase 1 must list regions BEFORE reading them, and add >=1 candidate not from seeds>
Rules:           §6 of this plan (fix invariants), §6.1 enforcement commands, §7.4 live-call prohibition
Output:          tasks/audits/defect_hunt_v71_w<N>_<surface>.md with the labelled PHASE 0..8 headers verbatim,
                 plus the uncertainty acknowledgment; append records to tasks/audits/candidates.yml
```

### 7.2 Wave lifecycle

1. **Branch** `claude/defect-hunt-v71-w<N>-<surface>` from the current `main`; confirm the §2.5 baseline.
2. **Phases 0-Wave through 4** (read-only plus throwaway reproducer tests): regions, candidates, trigger tests,
   innocence attempts, triaged inventory. Commit the report and the inventory records only. **Stop point 1:** the
   inventory is reviewed (by the user, or by a second pass on a different model) before any fix is written. This is
   where false positives are cheapest to remove.
3. **Phases 5–7:** fixes in inventory order, each with Placement, Mechanism, Conformance, Causal justification, Risk;
   self-review over the eight vectors; proof, boundary and no-regression tests. One commit per defect: fix and tests
   together, commit subject in the house style (for example `fix(flows): fail the session when a plan is rejected
   (finding H3.2)`).
4. **Phase 8:** process and engineering check tables, the coverage and residual-risk statement, the uncertainty
   acknowledgment, and the routing verdict (ACCEPT, RE-ITERATE, ESCALATE or PARTIAL).
5. **Gate:** unit suite, architecture tests and the §6.1 commands green; then a draft PR. **No merge or push without an
   explicit instruction from the user.**

### 7.3 Parallelism

Waves inside one group (§5) may run concurrently, each in its own git worktree and its own session, because their
surfaces are a partition. Concurrency is capped at **three sessions** to keep review tractable and token spend visible.
A wave never edits a file outside its surface; if a fix needs to, it stops with
`[REQUIRES HUMAN REVIEW: cross-boundary mechanism]`.

### 7.4 What the hunt must never do

- **No live provider calls.** Trigger tests run under `-m "not external"` with stubs that honour the layer's
  documented contract. Several `.env` keys are set on this machine and a billed call during a hunt is a real cost;
  OpenRouter credits are also currently exhausted, so live calls would fail anyway. A defect that can only be shown
  with a live provider stays `[UNK]` and goes to the runtime-instrumentation list.
- **No destructive actions on real data.** Reproducers use `tmp_path` databases and workspaces. The unit-test conftest
  already isolates `.env`, the memory directory, `OLLAMA_*` and the role-override file; new reproducers inherit it.
- **No touching the user's `.env`, `.weebot/`, or session databases.**
- **No raising a ceiling, adding an exemption, or loosening a lint to make a fix pass.**

### 7.5 Group-end gate

After the last wave of a group merges: run the full unit suite and the browser suite, re-run every proof test from the
group's waves against the merged tree, and run the fix-interaction check across the group's fixes (shared lines, shared
state, one fix changing another's trigger, two fixes wanting the same owner-layer change). Interactions found are
sequenced in a short note appended to the group's last report.

### 7.6 Tests

Follow the project's tiers. Pure domain code: unit tests in `tests/unit/domain/...`. Application services and flows:
unit tests with fakes, in the existing directory for that module. Adapters and persistence: integration-style tests with
a temp database. Boundary behaviour: tests at the web layer using `TestClient` with dependency overrides (the pattern in
`tests/unit/test_role_model_overrides.py`). Concurrency: a repeated-trial harness, N ≥ 100, labelled STATISTICAL.
Each defect gets at least three tests: proof-of-defect, two boundary tests, one no-regression test; plus a pattern-
contract test when a pattern was introduced.

---

## 8. Deliverables and records

| Artefact | Path |
|---|---|
| This plan | `tasks/specs/defect_hunt_v7_1_execution_plan.md` |
| Architecture and environment census (W0) | `tasks/audits/defect_hunt_v71_w0_census.md` |
| Cleared-register | `tasks/audits/defect_hunt_v71_cleared_register.md` |
| Last-audited manifest | `tasks/audits/defect_hunt_v71_w0_manifest.md` |
| Per-wave report | `tasks/audits/defect_hunt_v71_w<N>_<surface>.md` |
| Inventory (single source of truth) | `tasks/audits/candidates.yml` (`round: 2`, ids `H<wave>.<n>`) |
| Observation log (never counted) | `tasks/audits/defect_hunt_v71_observations.md` |
| Human-review queue | `tasks/audits/defect_hunt_v71_review_queue.md` |
| Programme statement (W12) | `tasks/audits/defect_hunt_v71_programme_statement.md` |
| Proof tests | alongside the existing suites under `tests/` |

The human-review queue lists every `[REQUIRES HUMAN REVIEW]` item with its reason (port change, migration, cross-boundary,
dependency defect, guard widening, unsolvable attack vector), so nothing needing a decision is buried in a report.

---

## 9. Termination and accounting

Per wave: the surface map is fully triaged, or `budget_spent` reaches the budget in §5. Counters are recorded in the
report header: `hunt_iterations` (cap 3 per region tier; exhausting it advances the queue), `fix_revisions` (cap 1;
exceeding it escalates), `budget_spent`.

Programme: **a partial programme is a valid result.** Priority order if time is short: W0, W1, W2, W3, W5, W7, then the
rest. W12 runs over whatever waves completed, and its statement says which did not.

Suggested cost envelope (token spend is the real limit): budgets of 15–30 candidates keep a wave to one long session.
A reasonable first commitment is **W0 plus Group A** (three runs), then reassess from the false-positive rate observed.

---

## 10. Seeds for round 2 (all **[HYP]** unless marked)

These came from the most recent work and live testing. They are entry material only; each wave's Phase 1 enumerates its
regions first and must add at least one candidate that is *not* from this list.

| Seed | Wave | Observation |
|---|---|---|
| S1 | W2 / W3 | After a backend restart, sessions persisted as `running` are never reconciled; the rail's "Active" group lists runs with nothing executing. **[VF]** observed live 2026-10-25. Property: a RUNNING session has a live task. Owner: `TaskRunner` / startup lifecycle. |
| S2 | W7 | Billing errors (HTTP 402) are retried like transient ones; the planner role has only OpenRouter-addressed models, so exhaustion of one account stops all planning although other provider keys are configured. Property: a non-retryable error terminates its retry loop and the cascade can use any configured provider. |
| S3 | W2 | `PUT/DELETE /models/roles/{role}` writes `.weebot/role_models.json` with a read-modify-write under a process lock only. Two backend processes could lose an update. Property: concurrent writers do not lose picks. |
| S4 | W7 / W10 | Role-override precedence: `get_model_cascade_for_role` is the only reader that applies overrides. `role_model_selector`, `harness_profile_resolver` and `task_model_router` read `ROLE_MODEL_CONFIG` directly, so some decisions ignore a user's pick. **[VF]** by grep; the consequence is [HYP]. Property: one source of truth for the model of a role (owner: `config/model_refs`). |
| S5 | W6 | Session lessons are stored per project key `working_dir`; the planner reads `context.get("working_dir")` while the flow records `str(context.working_dir)`. If the two differ in form, lessons are written under one key and read under another. Property: write key equals read key. |
| S6 | W4 | `GetPlanVisualizationHandler` returned a shape the consumer could not read (fixed in `86289a08`). Other query handlers may have the same producer-consumer drift. Hunt: every `QueryResult.ok({...})` shape against its router and its UI/TS type. |
| S7 | W3 | `PlanActFlow.run` breaks its loop only on COMPLETED, WAITING or FAILED, or when the state is IDLE. Any state that returns without changing either re-enters at once (fixed for planning). Hunt the other twelve states for the same shape. |
| S8 | W1 | The inbound-mail approval gate and the egress guard are the policy for untrusted content (`CLAUDE.md`). Verify they fail closed when their own dependency (store, LLM, clock) raises. |
| S9 | W8 | `count_events` chunks 500 ids per query; confirm behaviour on the SQLite variable limit and on ids that are not strings. |
| S10 | W9 | MCP servers connect once per process and the first `/run` waited for them (mitigated with an 8 s bound). Connection finishes in a shielded background task: check cancel-scope ownership at shutdown (`close_mcp_toolkit`) and the retry story when a server stays down. |

Round-1 near-misses worth keeping in mind (V7 §7.4): a linter hit is a *candidate*, never a defect. Fixing a finding
without an innocence attempt is a protocol violation.

---

## 11. Risks to this plan

| Risk | Assessment and mitigation |
|---|---|
| **False positives.** V7.1 treats flagging correct code as a defect of the protocol. | Stop point 1 (§7.2) puts a review between the inventory and any fix. Track the false-positive rate per wave and stop the programme if it exceeds one in three. |
| **Seeds bias the hunt.** | Phase 1 lists regions before reading seeds; at least one candidate must be independent. |
| **Cost.** Twelve waves of long agent runs is a large token spend. | Waves are independent and the programme is allowed to stop after any wave (§9). Start with W0 and Group A. |
| **Census wrong.** Fixes are placed using the census; a wrong census misplaces them. | Census lines are tagged by source. Where only layout supports a claim it is [HYP], and fixes that depend on it say so. |
| **The 15-line limit forces escalations** in large application modules (`plan_act_flow.py`, `_base.py`). | Expected; recorded as `[CONSTRAINT-FORCED ESCALATION]` and in the review queue. |
| **Concurrency findings are undecidable statically.** | STATISTICAL labelling; a large [UNK] residual is a correct result, not a failure. |
| **The edit-gate hooks on this machine** ask for stated facts before the first edit or write to each file, and `make` is missing. | Not a code risk, but it affects throughput. Waves state importers and the user's instruction when prompted, and run scripts directly. |
| **Later waves run on code earlier waves changed.** | Group-end gates and W12's re-sweep. |
| **Parallel sessions edit one checkout.** Seen today: two sessions shared one working tree. | One git worktree per concurrent wave; a wave commits only its own paths. |

---

## 12. Decisions for the owner of the programme

1. **Fix policy per wave:** (a) wave writes fixes on a branch and opens a draft PR (recommended), or (b) wave only
   produces the inventory and fixes are applied separately after review.
2. **Starting point:** W0 plus Group A (recommended), or the full programme.
3. **Concurrency:** one session at a time, or up to three inside a group.
4. **Second reviewer for stop point 1:** the user, or an independent second pass on another model.
5. **Whether W11 (periphery) runs at all.**

---

## Appendix A — Commands behind the [VF] claims

```bash
git log --since=2026-09-05 --oneline | wc -l                                   # 317
git log --since=2026-09-05 --name-only --pretty=format: -- weebot cli          # churn per package
find weebot -name '*.py' | xargs cat | wc -l                                   # lines (per package: loop over dirs)
.venv/Scripts/python.exe -m pytest tests/unit -q -p no:cacheprovider           # 6271 passed, 104 skipped, 3 xfailed
.venv/Scripts/lint-imports.exe                                                 # 10 kept, 0 broken
.venv/Scripts/python.exe scripts/lint_import_exemptions.py                     # 62 at ceiling; 15 dynamic at ceiling
grep -E "status:" tasks/audits/candidates.yml | sort | uniq -c                 # 87 fixed, 13 cleared
grep -oE "weebot/[a-z_]+/[a-z_]+" tasks/audits/candidates.yml | sort | uniq -c # round-1 locations
```

## Appendix B — Uncertainty acknowledgment

- **Least certain claim:** the wave line counts. They are sums of package line counts and the services split is
  approximate until W0 freezes the file lists; budgets are sized from them and may need adjusting after W0.
- **Most likely omission:** `application/services` is the largest package and is cut into two waves by judgement;
  a defect that depends on both halves is a W12 seam candidate.
- **Census claims most likely wrong:** "dominant paradigms" is inferred, not documented [HYP]; the pattern locations
  are the ones I could name without searching the whole tree, and W0 may find better examples or fewer.
- **Needs runtime validation:** S1 (stale RUNNING sessions) and S10 (MCP shutdown ownership) cannot be settled by
  reading code alone.
- **What would raise confidence most:** a second reader on the Wave 0 census, and a decision on §12 before W1 starts.
