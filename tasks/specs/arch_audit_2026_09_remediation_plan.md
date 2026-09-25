# Architecture Remediation — Path to 9+

Follows the ARCH-AUDIT-V2 static audit of `35270df` (2026-09-09), which scored the
codebase **6/10** against the repo's self-reported 9.0 (`ARCHITECTURE.md`) and 9.6
(`docs/adr/ARCH-AUDIT-V2-DEFECTS.md`). This plan closes that gap.

**This is a plan, not an implementation.** Nothing here has been executed.

**Supersedes / subsumes.** Where these overlap, this plan wins and the older document
should be marked superseded rather than deleted:

- `docs/ARCHITECTURE_REMEDIATION_PLAN.md` and `_V2.md` — debt items D1–D6, two of which
  regressed (see §1.3)
- `docs/architecture_score_improvement_plan.md`, `_v3.md`
- `tasks/specs/pre_existing_architecture_debt_plan.md`
- `tasks/specs/ssot_constants_remediation_plan.md` — absorbed as Phase 3.2

**Depends on.** `tasks/specs/review_gate_and_residual_work_plan.md` Part A. If `main`'s
merge gate is not actually live, Phase 0.1 below is the first thing to fix and everything
else waits.

---

## 1. The thesis

The review-gate plan established: *you cannot build a gate on an instrument that cannot
fail* — repair the instrument, then require it. That programme worked. Seven contracts
run on every PR, 56 fitness tests gate merges, the debt ratchets are exact-equality in
both directions, and the three defects from the July audit were each genuinely applied.

The audit found the failure mode that survives all of it:

> **A dependency that is registered but never resolved is indistinguishable, from the
> outside, from one that works.**

Every existing instrument is *static*. Import-linter reads the import graph. The fitness
tests read the AST. Both answer "is this module allowed to reference that one" — and both
answer *yes* for a collaborator that is imported, registered, constructed at startup, and
then never passed to the object that needs it.

That is not hypothetical. Three separate controls are in exactly that state:

| Control | Registered | Reaches its consumer | Consequence |
|---|---|---|---|
| `LLMPool` — global LLM concurrency bound | `di/__init__.py:263` | **No** — `_base.py:283-290` omits `llm_pool=` | Unbounded branch (`_cascade.py:292`) is the only one ever executed |
| `trust_report_service` | `di/__init__.py:167` | **No** — field never assigned | ~40 lines in `states/completed.py:379-462` unreachable |
| `event_pipeline` (WP-4 middleware) | `di/__init__.py:234-235` | **No** — field never assigned | Chain built at startup, discarded |

Ten further DI keys have zero resolution sites; four of those are actively bypassed by
consumers that kept a direct import, so the DI-configured variant — with its retry policy,
model choice and cost tracking — never applies.

`tasks/audits/weebot_architecture_audit_v3.md` asserts at lines 109, 133 and 178 that the
first of these is wired and verified. It is not. **The most expensive defect in this
codebase is not any of the three; it is that the evidence trail records them as working.**

So the ordering throughout is: **build the wiring instrument, then wire.** Never the
reverse — otherwise Phase 1's fixes are as unverifiable as the things they replace.

### 1.1 Why this is worth doing at all

The boundaries are real. This is not a rescue job:

- **Domain purity survives an AST audit.** 87 files, 8,222 lines, zero imports of
  `infrastructure`/`application`/`interfaces`/`core`/`tools`, zero framework imports. The
  only third-party package anywhere in the domain is `pydantic`. That is rare and it is
  the expensive half of hexagonal architecture — already paid for.
- **Enforcement is merge-blocking**, not advisory: `.github/rulesets/main.json` lists
  `Lint + Architecture` as required with `enforcement: active`, `bypass_actors: []`.
- **The ports abstraction already earns its keep where it matters.** `PostgreSQLStateRepository`
  exists (`di/_factories.py:40`). The scalability work in Phase 5 is an adapter swap plus
  a scheduler extraction, not a rewrite. Most codebases at this score cannot say that.

The score is 6 because of hollow controls and a single-node ceiling, not because the
architecture is wrong. That is a much better problem to have.

### 1.2 What ">9" actually requires

The rubric is not a vibe. Reading it literally:

> 10 = All layers correctly separated, patterns consistent, observable, testable, **scalable**
> 8 = Minor drift in 1–2 modules, **no critical violations**

So >9 has three hard gates, and cleanup alone reaches none of them:

1. **Zero critical violations** → Phase 1.
2. **Consistent patterns, ≤2 modules with drift** → Phases 2–4.
3. **Scalable** → Phase 5. *This is unavoidable.* A system that can only ever run one API
   replica is not scalable, however clean its imports. Any plan promising >9 without
   Postgres and a scheduler extraction is mis-selling.

Phases 0–4 land the codebase at a defensible **8.5**. Phase 5 is what buys the last point,
and it is the largest single piece of work here.

### 1.3 Two documented targets moved backwards

Worth naming, because it sets the standard for how this plan tracks itself.
`ARCHITECTURE.md` records debt items D4 (`plan_act_flow.py` 972 lines, target ≤700) and
D5 (`_base.py` 1,042 lines, target ≤650). Measured at `35270df`: **983** and **1,083**.
Both grew. Neither approached target.

Likewise the import exemptions: ADR-001 records 52, `ARCHITECTURE.md` D3 records 35
against a target of ≤25, and the file today holds **67** — measured per-commit from git,
rising 53 → 67 over six weeks with a peak of 72.

**Correction to process:** every numeric target in this plan is expressed as a ratchet in
`tasks/quality/ceilings.toml`, not as prose in a markdown file. Prose targets in this repo
have a measured 0% hit rate. Ratchets have a measured 100% hold rate. Use the mechanism
that works.

---

## 2. Design approach

The user asked for optimal paradigms and patterns. The honest answer has two halves, and
the second matters more.

### 2.1 Patterns to apply, and why each is the right one here

| # | Pattern | Applied at | Replaces | Why this one |
|---|---|---|---|---|
| P1 | **Composition Root validation** (fail-fast assertion over the object graph) | `application/di/`, new test | String-keyed registration with no resolution check | Directly kills the failure class in §1. Cheap, and it is the instrument every later phase is verified by |
| P2 | **Typed keys** (phantom/generic key type instead of `str`) | `Container.register/get` | `register("llm_pool", …)` | A typo'd or orphaned string key is invisible; an orphaned typed key is a type error. Removes the class rather than the instance |
| P3 | **Separated Interface** (Fowler) | `application/abstractions/` | Three fields typed `Any` to dodge the `services`↔`flows` cycle | The seam already exists in-tree. Moving shared protocols there dissolves the cycle *and* restores the types — one change, two defects |
| P4 | **Parameter Object, fully typed** | `models/plan_act_flow_config.py:55,111,155` | `Any`-typed config fields | With real types, a checker catches every unassigned collaborator. This is what makes F4 impossible to repeat |
| P5 | **Interface Segregation** — narrow `FlowContext` Protocol | `flows/states/*` | 299 `context._private` accesses into the coordinator | States currently get the whole flow object and mutate `context._plan` directly. A narrow protocol makes the state machine testable in isolation, which the rubric asks for by name |
| P6 | **Bulkhead + backpressure** | `services/task_runner.py`, `_cascade.py` | Fire-and-forget `create_task`; inert semaphore | Two independent ceilings (flows, LLM calls) so neither can saturate on the other's behalf. Standard resilience pattern, correct here |
| P7 | **Anti-Corruption Layer** | `flows/states/verifying.py:19`, `_cascade.py:142-149,552-558` | `from openai import …` in the application layer; raw `httpx` to OpenRouter | Provider exceptions and HTTP shapes are the vendor's model leaking inward. The port already exists — the ACL is where the leak is translated |
| P8 | **Registry consolidation / SSOT** | three model catalogs | `config/model_registry.py`, `services/model_registry/_catalog.py`, `config/model_refs.py` | Three live catalogs with disjoint callers and no reconciliation is a correctness hazard, not a style issue |
| P9 | **Fail-closed default** (secure-by-default) | `interfaces/web/auth.py:55-59` | Any header value mints a valid principal | Store mode already validates six lines below. The fix is to make the default behave like the non-default |
| P10 | **Leader election / single-writer election** | scheduler extraction | Scheduler in every API replica, no lock | Prerequisite for replica count > 1 |
| P11 | **Architecture fitness functions** | `tests/unit/test_architecture_fitness.py` | Prose targets | Each invariant this plan establishes ships with the test that prevents its regression |

### 2.2 Patterns deliberately NOT applied

This section exists because the codebase's dominant failure is *too much* indirection, not
too little. Adding patterns here would lower the score.

- **No new ports.** 46 of 68 ports have exactly one implementation, and 43 of those have
  no test double either — roughly 1,400 lines of indirection buying nothing. Phase 4
  *deletes* ports. ADR-006 already set this precedent; it was under-applied.
- **No abstract factory / strategy layer over the model catalogs.** The defect is three
  sources of truth, not a missing abstraction. Consolidate to one concrete registry.
- **No event-sourcing expansion.** CQRS + event store already exist and work. Widening
  them adds surface without addressing any finding.
- **No microservice split.** The audit found no hidden monolith. Phase 5's scalability
  problem is state locality, and extracting the scheduler is a *process* boundary, not a
  service-decomposition programme.
- **No repository/UoW rework.** `StateRepositoryPort` has three implementations and is one
  of the ports genuinely earning polymorphism. Leave it.

### 2.3 Paradigm note

Keep the domain as it is: immutable-ish Pydantic aggregates with behaviour on the
aggregate (`Plan`, `Step`, `Session`, `Skill` already carry real invariants and state
transitions). The audit found the domain **bimodal, not anemic** — 161 of 184 non-enum
classes are DTOs, but the core aggregates are healthy. Do not "fix" the DTO periphery;
`domain/models/event.py` (528 lines, 42 classes, 0 methods) is a message catalogue and
that is the correct shape for one.

---

## 3. Phase 0 — Instruments

**Nothing in later phases is trustworthy until this lands.** Every item here is small.

### 0.1 Make branch protection verifiable — BLOCKING

`Protection Drift` has failed daily since at least 2026-09-06. By design it fails closed
when it cannot read live protection (`protection-drift.yml:10-13`), so today it reports
*unknown*, not *drifted*. Until it goes green, the statement "import-linter is a required
check" is unverified — and that statement is load-bearing for this entire plan.

- Issue a PAT with `administration:read`, store as `PROTECTION_READ_TOKEN`.
- Confirm the job distinguishes **CANNOT VERIFY** from **DRIFTED** in its exit path; if it
  does not, split the exit codes so the red has a meaning.
- Green, or a written record of the actual drift.

**Exit:** `Protection Drift` green, or an issue documenting real divergence from
`.github/rulesets/main.json`.

### 0.2 Composition-root wiring assertion — the new instrument (P1, P2)

The centrepiece. Two parts:

**(a) A resolution census test.** Enumerate every `register`/`register_instance` call in
`application/di/`, and assert each key is either resolved somewhere in `weebot/` or `cli/`,
or carries an explicit `optional=True` with a one-line reason.

```
FAIL: DI key 'llm_pool' is registered at di/__init__.py:263 but never resolved.
      Either resolve it, or mark it optional with a reason.
```

This single test would have caught all three §1 controls, and catches the next one for
free. Seed its allowlist with today's ten orphans so it goes green on introduction, then
empty the allowlist in Phase 2.4 — the ratchet discipline already used for ceilings.

**(b) Startup graph validation.** In the composition root (`interfaces/factories.py`,
`interfaces/web/main.py` lifespan), after wiring, assert that collaborators the system
claims to have are actually present. Fail fast and loudly at boot rather than degrading
silently at load.

> **Design note.** Prefer (a) as a test over (b) as a runtime check where possible —
> a CI failure is cheaper than a production boot failure. Use (b) only for things that
> cannot be determined statically.

**Exit:** new test in `tests/unit/test_architecture_fitness.py`; ceiling
`unresolved_di_keys = 10` in `ceilings.toml`.

### 0.3 Make the fitness suite fast and deterministic

`tests/unit/test_architecture_fitness.py:1624` calls `root.rglob(...)` over the whole
repository and **exceeded a 60s timeout locally**. It is scanning `node_modules`, `.git`,
and a 30 MB vendored tree.

- Scope the `rglob` to `weebot/` and `cli/`.
- `git rm -r --cached weebot/GitNexus-main/` — 318 files, 29.8 MB, **~65% of the tracked
  tree**, already listed at `.gitignore:59` but tracked, so the ignore rule is inert
  (gitignore does not apply to tracked files). It is never imported as Python and has no
  `__init__.py`, so it does not ship in the wheel; it is invoked as an external binary.
  Removing it also drops four tool-config special cases (`pyproject.toml:40,92`,
  `Makefile:96`, `pytest.ini`).
- History rewrite is **out of scope** — stopping the bleed is not.

**Exit:** full fitness suite runs under 60s in CI and locally.

### 0.4 Coverage: measure, then ratchet

The gate is `--cov-fail-under=52`. Do not guess a target. Measure actual coverage, set the
ceiling to the measured value under the same exact-equality rule as `ceilings.toml`, and
drive it up in later phases. A ratchet that tracks reality beats a round number nobody
chose.

**Exit:** `coverage_floor` in `ceilings.toml`, `--cov-fail-under` reading from it.

### 0.5 Pin the replica constraint

Phase 5 removes the single-node ceiling. Until then, record it where it can be acted on:
a comment in `docker-compose.yml` next to `weebot-api` stating that replica count must
remain 1 until the scheduler is extracted and state is shared, with a pointer to §8.
Cheap, and it prevents an accidental scale-out between now and then.

---

## 4. Phase 1 — Critical violations

Security first. Each item ships with the fitness test that prevents its return.

### 1.1 Fail-closed authentication (P9) — CRITICAL

`WEEBOT_AUTH_MODE` defaults to `"legacy"` (`auth.py:31`). In legacy mode
`get_current_user_id` (`:55-59`) takes any non-empty `X-API-Key`, returns
`f"key-{sha256(api_key)[:16]}"`, and **never calls `_get_legacy_api_key()`**. The store-mode
branch six lines below (`:63-71`) *does* compare. The async resolver delegates straight
back to the unvalidated path whenever legacy mode is on (`:87-88`).

Consequence: `require_mutation_identity` (`:159-172`) rejects only `"anonymous"` from
non-loopback hosts, so any attacker-chosen header value mints a stable non-anonymous
principal and reaches mutating endpoints on a service whose agent executes shell and
browser actions.

**Fix.** In legacy mode, compare against `_get_legacy_api_key()`; return `"anonymous"` on
mismatch. If no key is configured, fail closed rather than minting a principal.

**Do not** simply flip the default to store mode as the whole fix — that changes the
deployment contract for existing users and leaves the broken branch in place for anyone
who sets it back.

**Tests.** Wrong key → `"anonymous"`. No key configured → `"anonymous"`. Correct key →
stable principal. Non-loopback + wrong key + mutating endpoint → 403.

**Risk:** low, blast radius narrow. **Rollback:** revert; one file.
*Calibration for whoever schedules this:* the derived principal is distinct per key value
and `verify_session_ownership` scopes sessions to it, so this is unauthenticated **use** of
the agent, not cross-tenant reads. Still first in the queue — the agent runs code.

### 1.2 Unify the MCP trust-boundary prefix — CRITICAL

`core/trust_boundary.py:125` sets `_MCP_NAMESPACE_PREFIX = "mcp__"`.
`services/mcp_tool_registry_bridge.py:26` produces that correctly. But
`infrastructure/mcp/mcp_client_manager.py:195-197` builds
`prefix = server_name if server_name.startswith("mcp_") else f"mcp_{server_name}"`, then
`f"{prefix}_{tool.name}"` — yielding `mcp_xapi_search`, which fails the `mcp__` test. Same
single-underscore construction at `mcp_tool_bridge.py:107`.

Those names become live tools (`mcp_toolkit_adapter.py:41-50` →
`interfaces/factories.py:287-288`), so their output is neither wrapped in the
prompt-injection fence nor marked as tainting egress — the exact control `CLAUDE.md`
requires for untrusted inbound content.

The literal fallback does not rescue it: `UNTRUSTED_OUTPUT_TOOLS` contains `"mcp_tool"` and
`"mcp_call"` (`trust_boundary.py:82-83`), but those two strings occur **nowhere else in the
codebase** — no tool is registered under either name. The guard list covers two names that
do not exist.

**Fix.** Emit `mcp__` at the source (`mcp_client_manager.py:195-197`, `mcp_tool_bridge.py:107`).
Delete the two dead literals. Do **not** widen the prefix match to `mcp_` — that would make
any future tool starting with those four characters silently untrusted, which is the same
class of accident in the other direction.

**Test (invariant, not instance).** Enumerate every registered tool whose name originates
from an MCP source and assert `is_untrusted_tool(name)` for each. This is the form that
survives a future third naming site.

**Risk:** medium — tool names are user-visible and may appear in persisted sessions or
skill definitions. Check for stored references before renaming; add a migration or an
alias map if any exist.

### 1.3 Bulkheads: bound flows, then wire the pool (P6) — CRITICAL

Two ceilings, both currently absent. Do them together; either alone leaves the other
unbounded.

**(a) Bound concurrent flows.** `task_runner.py:123-126` does `asyncio.create_task(...)`
and `_start_direct` returns at `:158` without awaiting. The worker loop (`:65-77`) therefore
drains the queue at memory speed into `self._tasks`, an unbounded dict of running flows.
`InMemoryTaskQueue`'s `maxsize=100` bounds a waiting state the system never reaches.
Add a semaphore or an explicit `len(self._tasks)` ceiling so the queue's limit can actually
apply backpressure.

**(b) Wire `LLMPool`.** Pass `llm_pool=` at `_base.py:283-290`.

> **Caveat, load-bearing.** This activates a 120s acquire timeout (`llm_pool.py:51`) that
> has **never executed in production**. Under (a)'s new flow ceiling the queue depth
> changes shape too. Load-test before shipping; consider making the acquire timeout
> configurable with a generous initial value.

**(c) Correct the record.** Amend `tasks/audits/weebot_architecture_audit_v3.md:109,133,178`,
which certify the opposite. Per §1 this is the actual defect — leave it and the next audit
inherits the same false premise.

**Verification:** Phase 0.2's census must show `llm_pool` resolved, not allowlisted.

**Exit for Phase 1:** zero critical findings; each covered by a fitness test; `ARCHITECTURE.md`
and `audit_v3` corrected. **Score: ~7.5.**

---

## 5. Phase 2 — Root cause: the cycle and the erased types

Phase 1 fixed three instances. This phase removes the condition that produced them.

### 2.1 Dissolve the services↔flows cycle (P3)

Seven distinct workarounds exist for one cycle, each documented in-tree: a module
`__getattr__` shim (`tools/base.py:19-27`), a deliberately empty package init
(`application/services/__init__.py:3`), a package that exists solely to break it
(`application/abstractions/__init__.py:4`), a DI registry indirection (`di/__init__.py:191`),
inline flow construction (`adapters/sub_agent_factory.py:73`), lazy metric imports, and the
type erasure below.

`application/abstractions/` is already the correct seam. Move the shared protocols there so
`services` and `flows` both depend on abstractions and neither on the other. Then delete
the workarounds the cycle forced — each removed shim is a permanent simplification.

**Do not** treat the 30 `# noqa: E402` markers in `di/__init__.py:26-66` or those in
`plan_act_flow.py:45-68` as cycle evidence. They follow a statement placed before the
imports. Leave them.

### 2.2 Restore real types on `PlanActFlowConfig` (P4)

`models/plan_act_flow_config.py` types `mediator` (`:55`), `trust_report_service` (`:111`)
and `event_pipeline` (`:155`) as `Any` *explicitly* to dodge the cycle. Two of the three are
never assigned anywhere in the repo. With real types a checker catches that class outright.

Depends on 2.1. **This is the single highest-leverage item in the plan** — it converts a
silent runtime nothing into a compile-time error.

Add `mypy` (or `pyright`) over `application/models/` and `application/di/` at minimum, as a
ratcheted gate consistent with existing practice.

### 2.3 Decide the dead features: wire or delete

Now decidable, because 2.2 makes "unassigned" visible.

- **Trust reports** — port, service (`services/trust_report_service.py:23`), domain model, DI
  registration and factory all exist; `states/completed.py:379` guards ~40 lines on a field
  nothing assigns. Either assign it in the composition root, or delete service, port, model,
  registration and the guarded block.
- **Event pipeline (WP-4)** — built and registered at `di/__init__.py:234-235`, read at
  `plan_act_flow.py:218-219`, used at `:460`. Same call.
- **Ten further orphan keys.** Four (`idea_gate`, `intent_review`, `main_review`,
  `skill_curator`) are bypassed by consumers holding direct imports — for those, remove
  *either* the binding *or* the direct import. Keeping both is the worst of the three states.

**Guidance:** default to **delete**. A feature nobody noticed was missing for months is not
a feature. Deletion is reversible via git; carrying dead code is not free.

### 2.4 Empty the Phase 0.2 allowlist

Ratchet `unresolved_di_keys` to 0. From here the wiring class cannot recur.

**Exit:** no `Any`-typed collaborators; cycle workarounds removed; orphan keys at zero.
**Score: ~8.0.**

---

## 6. Phase 3 — Boundary integrity

### 3.1 Anti-corruption layer for providers (P7)

Three leaks of vendor detail into the application layer:

- `flows/states/verifying.py:19` — `from openai import AuthenticationError`. Translate to a
  domain/application exception at the adapter boundary; the state should catch *that*.
- `agents/executor/_cascade.py:142-149,552-558` — raw `httpx` calls to
  `openrouter.ai/api/v1`, bypassing `LLMPort` entirely. Move behind a port method
  (credit/catalog queries are legitimate capabilities — give them a named port, not a raw
  HTTP call from an agent).
- `services/model_registry/_catalog.py` — 1,049 provider-name occurrences inside
  `application/`. Addressed by 3.2.

**Preserve carefully:** `_cascade.py:451-471` documents a real, subtle billing defect —
first-completed selection preferentially picked the fastest *failure* (~200ms) over slower
successes, discarding already-billed results. Any refactor must keep those semantics. Pin
them with a test before touching the file.

### 3.2 One model catalog (P8) — absorbs `ssot_constants_remediation_plan.md`

Three live catalogs, disjoint callers, no reconciliation:

| Module | Lines | Consumed by |
|---|---|---|
| `config/model_registry.py` | 1,628 | `di/_factories.py`, `di/_skillopt.py`, routing, benchmark |
| `services/model_registry/_catalog.py` | 4,281 (generated) | `services/model_selection.py`, `config/_catalog_validator.py` |
| `config/model_refs.py` | 869 | cascade tiers, image, video, rerank |

Consolidate to one generated catalog plus one hand-maintained override file, owned by
`config/` (not `application/`). `_get_default_model_registry()` — **one function spanning
`:152` to `:1491`, ~1,339 lines** — dies with this.

Note the config oddity to resolve while here: `MODEL_FACTORY_OPENAI = "moonshotai/kimi-k2.6"`
and `MODEL_FACTORY_ANTHROPIC = "qwen/qwen3.8-max"` (`config/model_refs.py:289-290`) — provider
keys mapping to unrelated vendors' models. Either a naming bug or an undocumented
routing convention; determine which.

### 3.3 Close the path-scoped enforcement hole

Contracts are scoped by directory, so **moving code out of a governed path removes
governance with no gate firing**. `weebot/mcp/server.py` is an entry point (via `run_mcp.py`)
importing `weebot.infrastructure.*` and `weebot.tools.*` at `:61,:250,:375-378`. In
`interfaces/` those six edges would each need a reviewed exemption; at top level, no
contract applies at all.

- Move `weebot/mcp/` → `weebot/interfaces/mcp/` (it is an entry point).
- Add a **default-deny contract**: any top-level package under `weebot/` not explicitly
  assigned to a layer is forbidden from importing `infrastructure` and `tools`. New
  packages are then governed by default rather than by omission.
- Currently 9 such edges exist across the ungoverned packages (21,318 lines) — small today,
  unbounded in principle.

### 3.4 Drive exemptions down

67 today, rising. Set the ceiling at the measured value in `ceilings.toml` and lower it in
the same commit that removes each exemption. Phases 2–4 should remove a substantial share
as a side effect. **Do not** set an aspirational prose target — §1.3.

While here, correct `.importlinter:71`, whose comment claims a lazy import is "not detected
by import-linter". It is — grimp uses `ast.walk`, so nesting is irrelevant. The comment is
wrong and the exemptions it justifies are load-bearing, not decorative.

**Exit:** no vendor imports in `application/`; one catalog; every package under contract.
**Score: ~8.3.**

---

## 7. Phase 4 — Simplification (delete, do not abstract)

### 4.1 Delete confirmed-dead modules

- `infrastructure/interface_customization.py` — 1,218 lines, six responsibilities including
  ~150 lines of CSS embedded in Python and a `__main__` demo. **Zero importers**; the only
  textual match is an unrelated enum string.
- `templates/production.py` — 929 lines: four ORM tables, rate limiting, DB management,
  caching, health checks, and a hand-rolled `Authenticator:333`. No runtime importer.
  **Delete before someone wires it** — a bespoke authenticator in dead code is a latent
  trap, and Phase 1.1 exists precisely because auth in this repo has already gone wrong once.

### 4.2 Delete single-implementation ports

46 of 68 ports have exactly one implementation; 43 have no test double either. Apply
ADR-006's own rule properly: delete ports with one implementation and no planned
polymorphism. Retain the 18 with 2+ implementations (`LLMPort` 5, `SandboxPort` 5,
`NotificationPort` 3, `StateRepositoryPort` 3, …) and the four zero-implementation
structural `Protocol`s used as type constraints — those are correct.

Start with the clearest: `ports/gateway_session_store_port.py` defines **two** abstractions
for one concept in one file (a `Protocol` and an ABC) over a single concrete store. Also
review the 13 "ports" implemented by classes in `application/services/` or
`application/agents/` — an application-layer class implementing an application-layer port
is an interface to itself.

Write **ADR-013** recording the rule and why the earlier rationalization under-delivered
(2 deleted while the total grew 56 → 68).

### 4.3 Break up the two god methods

- `ExecutorAgent.execute_step` — `_base.py:463-983`, **521 lines in one method**.
- `PlanActFlow.run()` — ~270 lines, plus the class owning undo/redo, checkpointing, model
  switching and constraint extraction.

Extract along the seams ADR-007 already established (the `_cascade`/`_tool_executor`/
`_context_compressor`/`_error_handler` split worked). Encode both as ratchets in
`ceilings.toml` — `ARCHITECTURE.md`'s prose targets for these two files were missed and
both files grew.

### 4.4 Residual defects

Batch, low individual risk: reconcile the circuit-breaker thresholds (`_cascade.py:113`
trips at ≥5 but `:119-120` logs "tripped" at ≥3 — the log lies for two failures); fix
`_total_tokens = 0` (`plan_act_flow.py:829`, real value used at `:739`); cap the
live-model rescue price (`_cascade.py:578-585` picks the highest-context *paid* model at
runtime with no ceiling, and builds a fresh `Container()` inside the failure path at
`:594-596`); log-and-dead-letter the Redis `maxlen` eviction (`redis_task_queue.py:127`
silently discards oldest queued sessions); bound the write lock
(`connection_pool.py:187` uses a bare `async with`, asymmetric with the bounded read path
at `:222`); bound the two process-lifetime caches (`_cascade.py:61`,
`sqlite_state_repo.py:65`); add semaphores to the unbounded `asyncio.gather` sites
(`validation_runner.py:140-141` gathers whole flows; `optimizer_agent.py:83-94`).

Also resolve `CLAUDE.md` design rule 2 honestly: it mandates Pydantic-validated structured
output, but `WeebotOutput` has **zero production consumers** and neither `PlannerAgent` nor
`ExecutorAgent` validates against it. Either wire the two primary agents to it, or amend
the rule to describe what the system actually does. A mandate nothing follows is the same
fail-open class as everything else in this plan.

**Exit:** ~4,000 lines removed; no method over the ratcheted ceiling. **Score: ~8.5.**

---

## 8. Phase 5 — Scalability (this is what buys >9)

Three facts compound to make the system single-node:

1. State lives in a **process-local SQLite file** behind one write connection and one
   `asyncio.Lock` (`connection_pool.py:87,109,137,187`). A second instance is a second,
   divergent database.
2. The cron scheduler **starts inside the FastAPI lifespan** (`interfaces/web/main.py:203-208`),
   so every replica runs every job.
3. There is **no leader election** — a search across `weebot/scheduling/` and `main.py` for
   `leader`, `advisory_lock`, `SETNX` or an enable flag returns zero hits.

Sequence is forced:

### 5.1 Postgres as the state backend

`PostgreSQLStateRepository` already exists (`di/_factories.py:40`) — this is the payoff of
the ports architecture. Work is in migration, connection management and test coverage, not
in new abstraction. Note the other stores repeat the SQLite pattern independently
(`gateway_session_store.py:54`, `posterior_repository.py:78`, `sqlite_knowledge_graph.py:56`,
`sqlite_misalignment_journal.py:58`) — each needs the same treatment or an explicit decision
to stay local.

### 5.2 Extract the scheduler (P10)

Move it out of the API lifespan into its own process/service, or gate it behind a leader
lock (a Postgres advisory lock is the cheapest option once 5.1 lands). Until then replica
count stays at 1 — pinned in Phase 0.5.

### 5.3 Remove process-local assumptions

- `RedisTaskQueue`'s `FactoryRegistry` is per-process in-memory (`redis_task_queue.py:34-58`);
  its own docstring (`:10-13`) concedes multi-process workers must re-register or the
  session is dead-lettered.
- The 20+ ad-hoc `Container()` construction sites each build a *separate* object graph, so
  "singleton" scope is per-container, not per-process (`di/__init__.py:85`). A genuinely
  shared container exists at `interfaces/factories.py:59-71` but application code bypasses
  it. Route them through the shared root — this also fixes the documented cost at
  `services/background_tasks.py:5-12` (every CLI invocation building a container and
  starting LLM adapters for work then discarded).
- `HOME`-relative state (`docker-compose.yml:48-53` documents `Path.home()` usage in
  `profile_manager`, `behavior_tracker`, `skill_registry`, `gateway_auth`) must move to
  explicit configured paths.

### 5.4 Narrow the flow context (P5)

The orchestrator is not stateless: `PlanActFlow` holds mutable per-run state and states
mutate it directly through **299 `context._private` accesses** (`completed.py` 67,
`executing.py` 67, `planning.py` 48, `updating.py` 35), including direct writes to
`context._plan` at `executing.py:582,630`. There is no state-facing interface —
`FlowState.execute(self, context: PlanActFlow, …)` (`states/base.py:64`) hands over the
whole object.

Define a narrow `FlowContext` Protocol exposing only what states legitimately need.
**Highest blast radius in the plan** — do it last, after 2.2 restores types and with the
56 fitness tests as the safety net. A session can already be resumed from storage; the goal
here is that a *flow* has no hidden state, which is what "stateless orchestrator" requires.

### 5.5 Prove it

Run two replicas. Assert: no duplicate cron execution, no divergent state, sessions
resumable across replicas. Add a CI job if feasible; the compose smoke test already
exists as a starting point.

**Exit:** replica count > 1 demonstrated. **Score: 9.0–9.3.**

---

## 9. Sequencing and risk

```
0.1 protection ──┐
0.2 wiring test ─┤
0.3 fitness perf ┼──> 1.1 auth ────┐
0.4 coverage     │    1.2 mcp ─────┼──> 2.1 cycle ──> 2.2 types ──> 2.3 wire/delete ──> 2.4 ratchet 0
0.5 replica pin ─┘    1.3 bulkhead ┘                                      │
                                                                          v
                           3.1 ACL ──> 3.2 catalog ──> 3.3 default-deny ──> 3.4 exemptions
                                                                          │
                                                                          v
                           4.1 delete ──> 4.2 ports ──> 4.3 god methods ──> 4.4 residual
                                                                          │
                                                                          v
                           5.1 postgres ──> 5.2 scheduler ──> 5.3 process-local ──> 5.4 context ──> 5.5 prove
```

Phase 1 items are mutually independent and parallelisable. Everything from 2.2 onward is
strictly ordered.

| Phase | Risk | Rollback | Notes |
|---|---|---|---|
| 0 | Low | revert | Config and tests only |
| 1.1 | Low | revert, one file | Verify no deployment depends on the current permissive behaviour |
| 1.2 | **Medium** | revert + alias map | Tool names may be persisted in sessions/skills — check first |
| 1.3 | **Medium** | revert | Activates a never-executed timeout; load-test |
| 2.1–2.2 | **High** | branch | Wide import surface; lean on fitness tests |
| 2.3 | Low | revert | Deletion is git-reversible |
| 3.1 | **Medium** | revert | Preserve `_cascade.py:451-471` billing semantics |
| 3.2 | **Medium** | revert | Three call-graphs converge; migrate one consumer at a time |
| 4.x | Low | revert | Mostly deletion |
| 5.1–5.3 | **High** | staged, feature-flagged | Data migration; needs a rehearsal |
| 5.4 | **Highest** | branch | 299 call sites |

---

## 10. Scoring ledger

Deltas are judgement against the stated rubric, not arithmetic. Recorded so the claim is
falsifiable rather than asserted — the failure mode this whole plan exists to correct.

| After | Score | What changed against the rubric |
|---|---|---|
| Baseline | **6.0** | 5 critical violations; scalability ceiling; hollow controls |
| Phase 1 | ~7.5 | Zero criticals. Still: drift, single-node |
| Phase 2 | ~8.0 | Root cause removed; wiring class cannot recur; types honest |
| Phase 3 | ~8.3 | Layers cleanly separated; enforcement has no directory-shaped hole |
| Phase 4 | ~8.5 | Patterns consistent; ~4k lines of indirection and dead code gone |
| Phase 5 | **9.0–9.3** | **Scalable.** Stateless orchestrator, shared state, elected scheduler |

Reaching 9.5+ would additionally require observability depth (tracing that survives the
early-return paths, per-session cost attribution) and a materially higher coverage floor.
Out of scope here; note it rather than promise it.

---

## 11. Definition of done

- [ ] `Protection Drift` green — live protection verified against the checked-in ruleset
- [ ] `unresolved_di_keys = 0` in `ceilings.toml`
- [ ] Zero findings at CRITICAL from a re-run of ARCH-AUDIT-V2
- [ ] No `Any`-typed collaborators in `PlanActFlowConfig`
- [ ] One model catalog
- [ ] Every top-level package under an import contract; exemption ceiling ratcheting down
- [ ] Two API replicas running with no duplicate cron execution and no state divergence
- [ ] `ARCHITECTURE.md`, `docs/adr/`, and `tasks/audits/weebot_architecture_audit_v3.md`
      corrected — **no document asserts a control that is not wired**
- [ ] Every invariant above has a fitness test or a ratchet; none has a prose target

---

## Appendix A — verification commands

```bash
# exemption count and trend
grep -cE '^\s*weebot\..*->' .importlinter
for c in $(git log --format=%h --follow -- .importlinter | head -12 | tac); do \
  echo "$(git log -1 --format=%ad --date=short $c) $(git show $c:.importlinter | grep -cE '^\s*weebot\..*->')"; done

# the wiring class — returns only registration sites when a key is orphaned
grep -rn "llm_pool" --include="*.py" weebot/ cli/ tests/

# port census
ls weebot/application/ports/*.py | grep -v __init__ | wc -l

# tracked bloat
git ls-tree -r -l HEAD | sort -k4 -n -r | head -20
git ls-files weebot/GitNexus-main | wc -l

# god methods
awk 'NR>=463 && NR<=983' weebot/application/agents/executor/_base.py | wc -l
```

## Appendix B — audit findings index

Traceability to the source audit. IDs match the ARCH-AUDIT-V2 report of 2026-09-09.

| ID | Finding | Phase |
|---|---|---|
| F1 | `Any`-typed config fields concealed unassigned collaborators | 2.2 |
| F2 | `LLMPool` never wired; audit_v3 certifies otherwise | 1.3 |
| F3 | Unbounded concurrent flows | 1.3 |
| F4 | `trust_report_service`, `event_pipeline` never assigned | 2.3 |
| F5 | Circuit-breaker threshold vs log disagree | 4.4 |
| F6 | Post-execute hook reports zero tokens | 4.4 |
| F7 | Live-model rescue uncapped | 4.4 |
| F8 | Redis stream silently drops sessions | 4.4 |
| F9 | Unbounded SQLite write-lock wait | 4.4 |
| F10 | Two unbounded lifetime caches | 4.4 |
| F11 | Unbounded `asyncio.gather` fan-out | 4.4 |
| F12 | MCP trust-fence prefix mismatch | 1.2 |
| F13 | Default auth mode never validates the key | 1.1 |
