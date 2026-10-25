---
status: done
date: 2026-10-25
note: from the 2026-10-25 EGFV audit (7/10, 10 ledger rows WB-01..WB-10); phases 0-3 and 6 executed the same day, see section 17 for what landed and where it deviated; phases 4 (agent-loop extraction) and 5 (replica proof) NOT started
---

# Architecture Remediation - 2026-10 wave 2

Follows the 2026-10-25 EGFV audit of `main` at 2026-10-25. That audit scored the code
**7/10**, up from the 4/10 measured on 2026-10-24, with these sub-scores:

| Dimension | Score | Why not higher |
|---|---|---|
| Separation of concerns | 1 | WB-01: the `application -> infrastructure` direction has no contract |
| Consistency with baseline | 2 | only LOW doc drift (WB-05, WB-08) |
| Coupling and dependency health | 1 | WB-03: four never-evicted session-keyed module globals |
| Testability and observability | 2 | WB-04: one dead gate, but seams/tests/tracing all present |
| Failure resilience and scalability | 1 | WB-02 unbounded path; WB-07 single replica |

The audit's evidence base is different from the previous one and this plan inherits it: the
2026-10-24 findings were mostly static reads, whereas this one executed the gates
(`lint-imports` 10/10 KEPT over 943 files and 5552 edges; `test_architecture_fitness.py`
62 passed / 1 skipped; eight ratchet scripts at their ceilings) plus an AST coupling walk
over 811 modules. Numbers below are measured, not quoted.

Nothing in this plan raises a ceiling. Every row that lowers a count says which ceiling moves
with it, because the ceiling contract is exact equality in both directions.

---

## 1. What this plan closes

| ID | Defect (audit severity) | Closed by |
|---|---|---|
| WB-10 | Three `tasks/audits/` records carry no `status`/`date`, so they index under "unknown"; the committed `tasks/_index.md` was stale and `make lint-map` exited 1 on a clean checkout (not in the audit; found while preparing this plan). The index is regenerated as of this plan, so the gate is green again; the records themselves are still unclassified | 0.1 |
| WB-04 | `test_every_query_has_handler` always skips -> CQRS query coverage is unguarded | 0.2 |
| WB-02 | `LLMPort` escapes the global bulkhead on 5 CLI entry points | 1.1 |
| WB-03 | Four process-global session-keyed containers with no eviction | 2.1 |
| WB-01 | No contract governs `application -> infrastructure`; 3 live leaks | 3.1 |
| WB-06 | `execute_step` 527 lines, `ExecutingState.execute` 509, `_base.py` 1083 | 4.1, 4.2 |
| WB-07 | One write connection, in-lifespan scheduler, no election -> replica 1 | 5.1-5.4 (owned by the 2026-09 plan) |
| WB-05 | `ARCHITECTURE.md:23` self-score contradicts `:4` | 6.1 |
| WB-08 | bare `os.getenv` in an application service | 6.2 |
| WB-09 | `BackgroundTasks.spawn` has no task-count cap (decision only) | 6.3 |

Target after Phases 0-4 and 6: **9/10** (SoC 2, Consistency 2, Coupling 2, Testability 2,
Resilience 1). 10/10 requires Phase 5's replica proof, which is not this plan's work.

## 2. Design approach

### 2.1 Pattern doctrine

The audit's Phase 1a.9 supplies the idiom inventory. Rule applied throughout: **finish an
existing pattern rather than introduce a second one**, and introduce a new pattern only where
two or more ledger rows share the root cause it would remove (none here does).

| Module | Existing idiom (citation) | Pattern to apply | What we explicitly do NOT introduce |
|---|---|---|---|
| `application/strategies/llm_pool.py` | Decorator/bulkhead already complete: `BoundedLLMAdapter` (`llm_pool.py:160`) | Complete it: the same decorator, applied at the remaining construction site. `Null Object` for the absent-pool branch so the `None` check disappears from `_cascade.py:307` | A proxy/factory-of-factories layer, an async context-manager base class |
| `application/services/model_registry/_service.py` | Factory (`create_adapter`) plus a selection Strategy (`_strategies.py`) | Factory Method returns a bare port; the **composition root** applies the decorator (`di/_factories.py:110`) so wrapping stays in one place | Wrapping inside the factory (two places would each have to remember) |
| `agents/executor/_tool_executor.py` | Repository replay already exists (`:230-242`); the in-memory copies are caches over the event store | Introduce one **Session Scope** object owning the four maps, with a lifecycle (`open(session_id)` / `close()`), replayed from the store | An LRU/TTL cache. Eviction must be lifecycle-bound: a TTL could drop taint and open the egress hole |
| `core/background_tasks.py` | `LLMPool` semaphore idiom (`llm_pool.py:74-114`) | **Bounded worker set** (semaphore + explicit queue depth) with a typed saturation error, mirroring `LLMCapacityExhaustedError` | An external queue/broker; the in-process owner is correct for this stage |
| `flows/states/executing.py` | Extract Collaborator (ADR-007 precedent); Template Method in `FlowState`; transition registry (`states/base.py:91`) | **Extract Collaborator** along the seams ADR-007 already created (`_step_result_handler`, `_iteration_guard`) | Event-sourcing rewrite, a new pipeline framework |
| `flows/plan_act_flow.py` | Facade over states + CQRS mediator; `models/plan_act_flow_config.py` already carries 38 config edges | Extend `PlanActFlowConfig` into a proper **Parameter Object** and move `__init__`'s body into a `from_config()` constructor | A new `Builder` class hierarchy |
| `application/cqrs` | Mediator + per-command handler modules | No change. Repair only the **test** that reads the old file layout | Expanding CQRS to the queries that were deliberately deleted (`queries.py:1-12`) |
| `.importlinter` | `forbidden` contracts with per-edge `ignore_imports` and a written reason each | Add one more `forbidden` contract in the same style; convert the AST test's filename allowlist to per-edge exemptions | Replacing import-linter with grep; `allow_indirect_imports` on a direction that must be direct |
| `infrastructure/persistence/` | Port + two adapters already selected in DI (`di/_factories.py:36-41`) | **Adapter swap via the composition root** (Postgres), same port, same tests | An ORM, a repository-of-repositories, dual-write |
| `scheduling/` | Scheduler started in the web lifespan | **Singleton-per-cluster** via an advisory lock (owner election), process extracted from the lifespan | A scheduler framework, Redis-as-lock-without-fencing |
| `tests/unit/test_architecture_fitness.py` | AST helpers (`_walk_py`, `_parse`) already shared | Extend the same helpers; keep tests pure-AST so they stay fast (suite runs in 5.2s) | A new meta-testing framework |

### 2.2 Two rules that shape every step

1. **One root cause, one change.** WB-01 and WB-02 both touch `create_llm_adapter`. The plan
   sequences WB-02 first so WB-01's gate has one fewer site to excuse (section 12).
2. **Each step lands with the gate that proves it red-then-green.** A step whose gate was
   already passing before the change is not a step; it is a claim.

---

## 3. Phase 0 - Instruments

### 0.1 WB-10: make `lint-map` green again

**Cause (VERIFIED).** `scripts/gen_tasks_index.py` groups records by frontmatter `status`; three
`tasks/audits/defect_hunt_v71_*.md` records carry `round`/`cleared_count`/`purpose` instead, so
they render under `## unknown (3)`. `python scripts/gen_tasks_index.py --check` exits 1 on
`main` as committed; regenerating the index when this plan was added made the gate green without
classifying them.

**Action.** Add `status: reference` and `date:` to the three records (they are registers, not
open work), then regenerate. Until that happens they sit in a bucket named "unknown", which is
how a record becomes invisible without anything failing.

**Verification.** `python scripts/gen_tasks_index.py --check` exits 0;
`make lint-map` exits 0.

**Effort** XS. **Blast radius** LOCAL. **Risk** none; worst case a record lands in the wrong
index group, visible in review.

### 0.2 WB-04: repair the CQRS query gate

**Cause (VERIFIED).** `tests/unit/test_architecture_fitness.py:249-253` looks for
`application/cqrs/handlers.py`, which no longer exists (split into `handlers/`), so the test
self-skips. The suite's single skip is this test.

**Action.** Point the test at the `application/cqrs/handlers/` package: collect `Query`
subclasses from `cqrs/queries.py`, collect `register_query_handler(<Type>` targets across the
package, assert the sets match. Keep it AST-only (no imports) so the suite keeps its 5s budget,
and delete the `pytest.skip` branch so a future layout change fails loudly instead of silently.

**Verification.** `pytest tests/unit/test_architecture_fitness.py -q` reports **0 skipped, 63
passed**; temporarily commenting one `register_query_handler` line makes it fail.

**Effort** S. **Blast radius** MODULE (CQRS). **Risk** the repaired test may expose a genuinely
unregistered query; that is the point and it is a real find, not a regression.

---

## 4. Phase 1 - Boundary completeness (security/cost boundary)

### 1.1 WB-02: one bulkhead, every port

**Current state (VERIFIED).** `di/_factories.py:110-133` wraps every adapter it creates
(`_bounded_llm`). `application/services/model_registry/_service.py:48-64` also creates one and
returns it bare; `cli/commands/flow.py:112,176,207,232,305` feeds that into
`create_flow(llm=...)`. The cascade's own slot acquisition (`_cascade.py:307-310`) still
applies, so the cascade path is bounded; the two direct `self._llm.chat` sites
(`_tool_executor.py:587`, `_context_compressor.py:246`) are not, when they hold the CLI adapter.

**Action.**
1. `ModelSelectionService` stops being a place that hands out unmanaged ports: `create_llm_adapter`
   takes an optional `bounded_by: LLMPool | None` and returns `BoundedLLMAdapter(inner, pool)`
   when one is supplied, otherwise the bare port (unchanged behaviour for tests that do not pool).
2. The five CLI sites pass `_container.get(LLM_POOL)`.
3. Delete the `is None` branch in the cascade by giving `BoundedLLMAdapter` a `Null Object`
   sibling (`UnboundedLLMPort`) used only where a pool genuinely cannot exist; `_cascade.py:307`
   then reads `async with self._llm_pool:` unconditionally. This is the "finish the pattern"
   half of WB-02: the `None` branch is what let an unbounded port look legitimate.

**Verification.**
- `pytest tests/unit/application/test_llm_pool.py -q` (bulkhead tests)
- new assertion: for each of the 5 CLI sites, the object passed to `create_flow` is a
  `BoundedLLMAdapter` (`unwrap_llm(llm) is not llm`)
- `python scripts/lint_di_wiring.py` stays `unresolved_di_keys: 0` (the new `LLM_POOL` consumer
  must be resolvable, and the census will now count it)
- `python scripts/lint_container_construction.py` must not move (7 -> 7)

**Effort** S. **Blast radius** SYSTEM (CLI runtime only, but the invariant is global).
**Risk** Medium-low: the pool can saturate and raise `LLMCapacityExhaustedError` in a CLI path
that previously never queued. Mitigation: the CLI builds one flow at a time, so saturation is
unreachable there; assert it with the existing pool test rather than reasoning about it.

**Ceiling movement:** none. `unresolved_di_keys` must stay 0, not rise to 1.

---

## 5. Phase 2 - State ownership

### 2.1 WB-03: give the session caches an owner

**Current state (VERIFIED).** `_tool_executor.py:136-143` declares `_TAINTED_SESSIONS`,
`_LOCAL_TAB`, `_WRITTEN_FILES`, `_HYDRATED` at module scope, keyed by session id, mutated at
`:192,234,240,534,541`. Production code never removes an entry; the only `discard`/`pop` calls
are in `tests/unit/test_session_security_state_durable.py:48-51`.

**Action.**
1. New `application/agents/executor/_session_scope.py`: `SessionScope` holding the four maps as
   instance state, with `open(session_id)`, `close()` (drops the entry), `tainted`,
   `mark_tainted()`, `local_tab`, `written_files`, `hydrated`.
2. `ToolExecutor` receives a `SessionScope` (default: a process-scoped singleton that the
   composition root registers, preserving today's dedupe across the per-step executor
   instances - each step builds a fresh executor, so the scope cannot be per-executor).
3. `close()` is called from the existing session-deletion orchestrator (the one that already
   purges stores) and from `CompletedState` when a session reaches a terminal state.
4. The store remains the record: `SessionScope.open()` still replays through the existing
   `_persist_flag`/event-store path, so eviction is safe.

**Constraint that must not be violated.** Taint is sticky for the *session*, not for the
process: `close()` may only be called when the session is finished or deleted, never on a timer,
and never while a step is in flight. A TTL here would reopen the egress hole the taint closes.

**Verification.**
- `pytest tests/unit/test_session_security_state_durable.py tests/unit/test_trust_boundary_registry.py -q`
- new test: 10,000 synthetic `open()`/`close()` cycles leave `len(scope) == 0` (the leak is
  otherwise untestable statically)
- new test: a mid-session `open()` still replays `tainted` from the store (the security property
  survives the refactor)

**Effort** M. **Blast radius** SYSTEM. **Risk** Medium: this file is on the tool-execution hot
path and holds a security control. Sequence it before 4.1/4.2 so the extraction works on a
smaller surface (section 8).

**Ceiling movement:** none directly. This row is what lifts coupling/dependency health 1 -> 2
once it lands and `test_...` proves no module-level session containers remain.

---

## 6. Phase 3 - Governance of the inward direction

### 3.1 WB-01: contract the direction that has none

**Current state (VERIFIED).** `lint-imports` reports 10 contracts, none of the form
`source_modules = weebot.application` + `forbidden_modules = weebot.infrastructure`. The only
guard is `test_architecture_fitness.py:815-854`, scoped to `application/services/`, with a
**filename** allowlist (`:824-832`) that exempts seven files entirely - so a new infrastructure
import inside `task_runner.py` is invisible. Live sites outside DI: `semantic_skill_retriever.py:57`
(constructs `NumpyVectorStore`), `model_registry/_service.py:56` (`create_adapter`),
`clawhub_importer.py:90` (lazy adapter import). Measured: 50 `application -> infrastructure`
edges, 44 of them inside `application/di/**` (legitimately the composition root).

**Action.**
1. Add contract `app-no-infrastructure` to `.importlinter`:
   `source_modules = weebot.application`, `forbidden_modules = weebot.infrastructure`,
   `allow_indirect_imports = True` (matching `app-no-vendor-sdks`), with per-edge
   `ignore_imports` carrying a written reason each - beginning with the 44
   `application.di.* -> weebot.infrastructure.*` composition-root edges, which are correct and
   should be stated as such rather than hidden.
2. Fix the three real leaks in the same change: `semantic_skill_retriever` takes its
   `VectorStorePort` from the caller (it already accepts one - delete the default construction);
   `create_llm_adapter` moves behind a port or is deleted in favour of `Container.get(LLMPort)`
   (see 1.1); `clawhub_importer` takes an injected adapter factory.
3. Rewrite `test_application_services_no_infra_imports` to exempt **edges**, not **filenames**,
   so the seven currently-ungoverned files become governed for every import except their named
   one.

**Verification.**
- `lint-imports --config .importlinter` -> 11 contracts, all KEPT
- `python scripts/lint_import_exemptions.py`: `import_exemptions` rises only by the number of
  composition-root edges deliberately stated, and that number is written into
  `tasks/quality/ceilings.toml` in the same commit (the one permitted direction of movement
  here, and it must be argued in the diff)
- `pytest tests/unit/test_architecture_fitness.py -q` still 0 skipped

**Effort** M. **Blast radius** SYSTEM. **Risk** Medium: step 2 touches a vector-store
constructor used by the skill retriever path (covered by `tests/unit/test_skill_*`), and step 1
will make previously-invisible edges visible - expect the first run to be red on more than the
three known sites, which is the value of the step.

**Decision needed:** Q1 (section 11).

---

## 7. Phase 4 - Orchestration decomposition (WB-06)

Both rows here are Accepted Debt already: `ARCHITECTURE.md`'s "Remaining Debt" table carries them
as D4 (`plan_act_flow.py` over its 700-line target) and D5 (`_base.py` over its 650-line target,
amended by DOC-3 to point at the `functions_over_150_lines` ratchet instead of prose). This plan
changes that only because 4.0 creates the test seam that made the extraction unsafe, and because
the ratchet pins the count at 28 while the two god methods grow.

### 4.0 The seam first: step-level behavioural test

**Action.** One test that drives `ExecutingState.execute` through a *scripted* executor
(canned `LLMResponse`s, a fake tool collection, in-memory state repo) and asserts the sequence of
mediator commands and emitted `AgentEvent`s for: success, tool error, model cascade exhaustion,
and a repetition trip (`_iteration_guard`). No network, no filesystem.

**Verification.** The test fails if `execute` reorders two of its phases; run it under
`pytest -q` in <2s.

**Effort** M. **Blast radius** NONE (additive). **Risk** Low, but it is M because the state
currently has 509 lines of untested ordering and the scripted executor has to be built.

### 4.1 `ExecutingState.execute` 509 -> <150

**Action.** Extract, in this order, each behind the seam from 4.0:
1. `_step_preamble.py` - context/tool assembly and prompt preamble (the same shape as the
   existing `_prompt_builder.py` in the executor; reuse it rather than duplicating).
2. `_inbound_gate.py` - the inbound-mail approval gate (`executing.py:300-320`) and the
   tool-approval flagging (`:496-508`), which is policy, not flow.
3. `_step_outcome.py` - result classification and the transition decision, returning a
   `Transition(target: StateId, ...)` (the registry shape `states/base.py:91` already implies).
`execute` becomes: preamble -> execute step -> classify -> return transition.

**Verification.** `python scripts/lint_long_functions.py --list` drops this entry; ceiling
`functions_over_150_lines` 28 -> 27 in the same commit.

**Effort** L. **Blast radius** MODULE. **Risk** High without 4.0, low with it. Do not combine
4.1 with 2.1 - both edit the tool-execution path.

### 4.2 `ExecutorAgent.execute_step` 527 -> <150, `_base.py` 1083 -> <800

**Action.** ADR-007's extraction was partial; finish it along the same seams. The audit's
coupling measurement names the reason it is hard: `_base.py` has fan-out 37 and
`PlanActFlow`/`PlanActFlowConfig` fan-out 44/38, so the code being extracted is entangled with
the loop's parameter object. So:
1. Promote `PlanActFlowConfig` to a real Parameter Object (it already carries 38 edges) and give
   `PlanActFlow` a `from_config()` classmethod; `__init__`'s 234 lines become field assignments.
2. Extract `_step_loop.py` (iteration + termination) and let `execute_step` delegate, the way
   `_cascade.py`, `_tool_executor.py`, `_context_compressor.py`, `_error_handler.py` already do.
3. Drop `_base.py`'s allowlist entry in `test_architecture_fitness.py:931-940` (1450 -> 800) as
   soon as it measures under it; the allowlist entry is the debt, the ratchet is the target.

**Verification.** `lint_long_functions` ceiling 27 -> 26 (or lower);
`tests/unit/test_architecture_fitness.py::test_god_modules_under_800_lines` passes without the
`_base.py` entry; the 4.0 seam test plus `pytest tests/unit/application -q` stay green.

**Effort** L. **Blast radius** MODULE. **Risk** High: this is the main agent loop. Land 4.0
first, then 4.1, then 4.2 in that order, each as its own commit with its own ceiling edit.

---

## 8. Phase 5 - Scaling (WB-07)

**This phase is not new work.** `tasks/specs/arch_audit_2026_09_remediation_plan.md` Phase 5
owns it, `docker-compose.yml:36-52` pins the current state with a written order, and the 2026-10
plan's Phase 8 deferred to it. Its ledger row is CRITICAL because it blocks the stated maturity
gate (`ARCHITECTURE.md:6`: "Production returns when Phase 5.5 passes"), not because anything is
broken today.

What this plan adds is the dependency ordering against the rows above, and one requirement that
Phase 5 must not lose:

1. **Postgres as the shipped adapter** (5.1) - already-selected branch at `di/_factories.py:36-41`;
   gate with `tests/integration/test_migration_schema_matches_app.py` and the persistence suite.
2. **Scheduler out of the lifespan** (5.2) - gate: two processes, one cron execution.
3. **Owner election with a fencing token** (5.3) - a lock without fencing permits the same job
   twice after a pause; gate: kill the leader mid-job and assert exactly one completion.
4. **Remove the remaining process-local assumptions** (5.4) - `InMemoryTaskQueue`,
   `InMemorySteeringAdapter`, `SessionScope` (from 2.1). **2.1 must precede 5.4**, and 5.4 must
   precede the two-replica proof (5.5), or the taint/egress control becomes per-process.
5. **Replica proof** (5.5) - two replicas, no duplicate cron, no divergent state.

**Do not** add `deploy.replicas` before 5.5; that is the exact failure the compose file warns
about.

---

## 9. Phase 6 - Docs tell the truth, and one decision

### 6.1 WB-05: one score per document

**Action.** `ARCHITECTURE.md:23` still asserts "6/10 -> Estimated: 7.5-8.0/10 (post-remediation)"
for the 2026-06-18 state, while `:4` records a measured 4/10 for a later state and disclaims
hand-typed scores. Replace the `:23` sentence with a pointer to the audit record, and add this
audit's 7/10 to `:4` so the header carries the current measurement.

**Verification.** `rg -n "7\.5-8\.0|Estimated: .*/10" ARCHITECTURE.md` returns nothing.
`make lint-map` unaffected.

**Effort** XS. **Blast radius** LOCAL. **Risk** none.

### 6.2 WB-08: `SecretAccessor` in the one place that skipped it

**Action.** `application/services/model_registry/_service.py:32,63` reads
`os.getenv(cfg.api_key_env)` and `os.getenv("OPENROUTER_API_KEY")` directly. Route both through
`SecretAccessor.get`. If 1.1/3.1 remove `create_llm_adapter` entirely, line 63 goes with it and
only `_usable()` remains.

**Verification.** `make lint-env-access`: `bare_env_reads` 70 -> 68 (two reads, exact), so the
ceiling moves in the same commit.

**Effort** XS. **Blast radius** LOCAL. **Risk** none.

### 6.3 WB-09: decide, do not build

`BackgroundTasks.spawn` (`core/background_tasks.py:46-51`) has no task-count cap. It is bounded
in practice by per-principal HTTP rate limiting and by `LLMPool` beneath. **Recommended: accept
and document**, with a metric (`pending` already exists as a property at `:64-66`) exported so
the population is observable before it is capped. Building the cap now is complexity an
Early-Production single-replica deployment does not need.

**Decision needed:** Q2 (section 11).

---

## 10. Phase 7 - Optional enhancements (not defects)

Each is small, each is grounded in something the audit observed, none is required for the
target score. Do them only after Phase 0-3.

| # | Enhancement | Why (audit observation) | Effort |
|---|---|---|---|
| E1 | Pass an explicit `max_tokens` at the cascade's two `self._llm.chat` sites (`_cascade.py:351,702`) instead of relying on the adapters' defaults (16384 at `openai_adapter.py:161`, 4096 at `anthropic_adapter.py:64`) | Cost bounding works today but is two layers below the orchestrator that decides to spend; making the bound visible at the cascade is what lets a per-tier budget be reasoned about | S |
| E2 | Hash the tool schema into `prompt_sha` (`llm_pool.py:309-321`) | Today the digest covers the system message only, so a tool-definition change looks like an unchanged prompt version | S |
| E3 | Emit an `LLMCallCompleted`-shaped record for cascade *saturation* (`outcome="saturated"` already exists at `llm_pool.py:228`) into the cost dashboard | Saturation is logged but not counted anywhere an operator sees | S |
| E4 | Add provider idempotency keys to `EffectLedger.record` when the provider supports them | `effect_ledger.py:16` states in writing that exactly-once needs one; today it is guarded, not guaranteed | M |

---

## 11. Decisions to resolve

| # | Question | Recommended | Alternative |
|---|---|---|---|
| Q1 | WB-01's contract: state the 44 composition-root edges as exemptions in `.importlinter` (exemption ceiling rises by ~44, argued in the diff), or move the composition root out of `weebot/application/di/` so the contract needs no exemptions? | **Exemptions.** Moving the container is a much larger change and the file is already the documented single composition root; a visible, written exemption list matches the house style | Move `di/` to `interfaces/` or a new `composition/` package |
| Q2 | WB-09: cap `BackgroundTasks.spawn` now, or accept + measure? | **Accept + export the metric.** Rate limiting and `LLMPool` bound the real resource; the cap buys little at this stage | Semaphore-bounded spawn (as `LLMPool`) |
| Q3 | 4.2: extract `_step_loop.py`, or stop at 4.1 and accept `_base.py` at 1083? | **Extract**, because the ratchet target (`<800`) already exists in the test and the 150-line limit is what forces it | Accept debt again; lower the allowlist to 1100 and defer |
| Q4 | Phase 5 timing: start now, or keep it in the 2026-09 plan's lane? | **Keep in that lane.** It is scheduled, owned, and pinned; starting it before 2.1 lands breaks the fencing requirement in 5.4 | Start 5.1 (Postgres) in parallel now |

## 12. Sequencing and interactions

| Order | Item | Why this position |
|---|---|---|
| 1 | 0.1, 0.2 | Instruments first; 0.2's repair is what makes later CQRS-adjacent changes safe, and 0.1 makes `make check` meaningful again |
| 2 | 1.1 (WB-02) | Rewrites `create_llm_adapter`, which 3.1 then has one fewer site to handle |
| 3 | 2.1 (WB-03) | Shrinks `_tool_executor.py` before 4.1 touches the same call path |
| 4 | 3.1 (WB-01) | Needs 1.1 done; its new contract will then pass on the first run except for the two remaining leaks, which 3.1 fixes in the same commit |
| 5 | 4.0 -> 4.1 -> 4.2 | Strictly ordered; 4.0 is the test seam both depend on |
| 6 | 6.1, 6.2, 6.3 | Documentation and one decision; no code coupling, do them any time after 3.1 (6.2's line 63 may vanish with 1.1) |
| 7 | Phase 7 (E1-E4) | Only after the target score is reached; they are optimisations, not debt |
| 8 | Phase 5 | 2.1 before 5.4, always |

**Merge conflicts to expect:** 2.1 and 4.1 both edit `_tool_executor.py`/`executing.py`; 1.1 and
3.1 both edit `model_registry/_service.py`. Land in the order above and do not batch them into
one PR - each carries its own ceiling edit, and a batched ceiling edit is exactly what
`--verify-not-raised` exists to catch.

## 13. Ceiling movements

| Ceiling | Now | After | Moved by |
|---|---|---|---|
| `import_exemptions` | 62 | 62 + (composition-root edges stated in 3.1) | 3.1 - the only rise in this plan, and it must be argued in the diff |
| `bare_env_reads` | 70 | 68 | 6.2 |
| `functions_over_150_lines` | 28 | 26 (then lower as 4.2 finishes) | 4.1, 4.2 |
| `unresolved_di_keys` | 0 | 0 (must not rise) | 1.1 |
| `container_construction` | 7 | 7 (must not rise) | 1.1 |
| `unit_coverage_floor` | 64 | 65+ | 4.0's seam test, 2.1's leak test |
| `string_di_keys` | 44 | unchanged (use `LLM_POOL`, an existing `Key`) | 1.1 |

## 14. Definition of done

- Every row in section 1 is closed, or is section 8's work with its gate pinned.
- `make check` and CI's `lint-and-arch` job are green on a clean checkout, and no `tasks/`
  record indexes under "unknown".
- No ceiling rose except `import_exemptions` in 3.1, with the argument in the diff.
- The audit score is 9/10 on the same five-dimension rubric (10/10 needs Phase 5's replica proof).
- `ARCHITECTURE.md` holds no hand-typed score that contradicts another line in the same file.
- The four session-keyed module globals are gone; a test proves the scope empties.
- `LLMPort` leaves the container wrapped on every path, and a test asserts it at the five CLI
  construction sites.

## 15. Verification commands

```bash
make lint-imports                                   # 11 contracts, all KEPT
python scripts/lint_import_exemptions.py            # import_exemptions, dynamic_weebot_imports
python scripts/lint_module_cycles.py                # must stay 0
python scripts/lint_di_wiring.py                    # unresolved/unregistered 0, string_di_keys
python scripts/lint_long_functions.py --list        # the two god methods gone
python scripts/lint_container_construction.py
python scripts/lint_settings_construction.py
make lint-env-access                                # 68 after 6.2
make lint-unawaited
python scripts/gen_tasks_index.py --check           # 0 after 0.1
python scripts/gen_map_index.py --check
pytest tests/unit/test_architecture_fitness.py -q   # 0 skipped
pytest tests/unit/test_session_security_state_durable.py tests/unit/test_trust_boundary_registry.py -q
pytest tests/integration/test_security_penetration.py -q
pytest tests/stress/ -q --timeout=120
python scripts/quality_ceilings.py --verify-not-raised --baseline origin/main
```

## 16. Risk register

| Risk | Where | Mitigation |
|---|---|---|
| 2.1's eviction drops taint and reopens egress | `_tool_executor.py`, `core/egress_guard.py` | Lifecycle-only `close()`; store replay keeps the flag; explicit mid-session replay test |
| 3.1 turns many edges visible at once and the branch stays red | `.importlinter` | Land 3.1 as its own PR; expect red on first run, fix the three real leaks inside it, state the composition-root edges |
| 4.1/4.2 reorder the agent loop silently | `executing.py`, `_base.py` | 4.0 first, and it must fail when two phases are swapped |
| 1.1 makes CLI paths queue on a semaphore | `cli/commands/flow.py` | One flow at a time per process; assert with the pool test, not by reasoning |
| Phase 5 started early breaks the fencing requirement | `scheduling/`, `persistence/` | 2.1 -> 5.4 -> 5.5 order is mandatory |

---

## 17. Execution record (2026-10-25)

Executed on `main` at `b9c4c378`, uncommitted at the time of writing. Where this section and
the sections above differ, **this section is what the code does**. All phases landed except
5 (replica proof), which stays in the 2026-09 plan's lane as decided.

### Landed

| Item | Result |
|---|---|
| 0.1 (WB-10) | Larger than the audit said: **9** records were unindexable, not 3, and `gen_tasks_index.py` *dropped* every record whose `status` it did not recognise -- silence, not failure. Fixed the generator (`unindexable()`, non-zero exit naming each record) and canonicalised the 9 statuses. `tasks/_index.md`: 133 visible records -> **142**. The generator now fails on an unrecognised status or a missing `date`, proved by calling `unindexable()` on a bad row. |
| 0.2 (WB-04) | `test_every_query_has_handler` scans `cqrs/handlers/` for `register_query_handler` calls. Suite went from **62 passed / 1 skipped** to **63 passed / 0 skipped**. Proved it can fail: commenting out the `GetCostSummaryQuery` registration made it report `Unregistered: GetCostSummaryQuery`. |
| 1.1 (WB-02) | **Changed approach** (see deviations). `ModelSelectionService.create_llm_adapter` is **deleted**; `Container.create_llm_for_model` is the public route and applies `_bounded_llm`. Updated 5 CLI commands, `run.py` and 3 `scripts/run_*_tasks.py`. New gate `test_the_adapter_factory_is_only_called_by_the_composition_root` (name-extent scan, both directions); proved by dropping a probe file into `scripts/`, which failed the gate with the exact path. |
| 2.1 (WB-03) | Four module-level session containers -> one `SessionScope` (`agents/executor/_session_scope.py`) with `open`/`close` lifecycle, `get_session_scope()` mirroring `core/background_tasks`. `ToolExecutor` takes it by injection. `close()` on terminal state (`CompletedState`) and on session deletion (`web/routers/sessions.py`). New tests: 10,000 `open`/`close` cycles leave the scope empty; marking is idempotent so the store gets one row; close drops the cache and the store is the record; the executor uses an injected scope. |
| 3.1 (WB-01) | New contract `app-no-infrastructure` (11 contracts, **11 KEPT**). Scoped to the 15 application subpackages with `application.di` excluded as the composition root, plus `test_every_application_subpackage_is_under_the_inward_contract` for default-deny. The 4 edges it flagged were **fixed, not exempted** (see deviations). `test_application_services_no_infra_imports` went from 7 filename exemptions to **zero**, with per-edge tracking if one ever comes back. |
| 6.1 (WB-05) | `ARCHITECTURE.md` no longer carries a self-score at `:16` or a stale pointer at `:4`; both name the audit records. `rg "7\.5-8\.0"` outside the new explanatory sentence returns nothing. |
| 6.2 (WB-08) | `_usable()` reads keys through `SecretAccessor`. `bare_env_reads` **70 -> 68** (measured), and the ceiling moved with it in `tasks/quality/ceilings.toml`. |
| 6.3 (WB-09) | Decided, not built: accept and document. No code change. |
| 4.0 (WB-06) | `tests/unit/application/flows/test_executing_state_scripted.py`: drives the real `ExecutingState` against a scripted mediator for success, tool error, cascade exhaustion, repetition trip, steering and a rejected command — no model, no network, no database, 7 tests in 0.4s. **It found a live bug on its first run** (below). |
| 4.1 (WB-06) | `ExecutingState.execute` **509 -> 96 lines**; `executing.py` **768 -> 284**. Three collaborators: `_execution_gates.py` (the five pre-step gates, in order), `_step_run.py` (the mediated call, event reconstruction, the inbound-mail flag), `_step_outcome.py` (failure routing, quality gates, completion, transition). `mark_user_gate` and `step_fetched_inbound_mail` moved with their only callers. |
| 4.2 (WB-06) | `ExecutorAgent.execute_step` **527 -> ~120 lines**; `_base.py` **1226 -> 766**, so its allowlist entry in `test_god_modules_under_800_lines` (1450) is gone and the default 800 applies again. Collaborators: `_step_setup.py` (prime + prompts, split because `yield StepEvent` lands between them), `_turn.py` (message assembly, cascade, the two typed declines), `_tool_batch.py` (`ToolBatchRunner`: the per-step counters that survive across turns, plus pre-flight, execution and the three per-result policies), `_tool_pairing.py` (`sanitize_tool_call_pairing`, moved verbatim by script rather than retyped). |
| 7 (E2) | `prompt_sha` now has a sibling: `tools_sha` (`llm_pool.py`), so a tool-schema change no longer looks like an unchanged prompt version in the `llm_call` record. |

### Deviations from the plan, and why

1. **1.1 became a deletion, and the Null Object was dropped.** The plan proposed wrapping the
   adapter in the service and replacing the cascade's `None` branch with an `UnboundedLLMPort`
   Null Object. A Null Object whose purpose is to look bounded while not bounding is the shape
   of the original defect: `llm_pool.py`'s own history is a bound that existed, was registered,
   and was never passed to anything. So instead: delete the second construction site, route the
   peer through the container, and add a **gate** (`test_the_adapter_factory_is_only_called_by_the_composition_root`)
   that fails on the next bypass. `_cascade.py`'s `None` branch is unchanged, and is now only
   reachable by a test or a harness.
2. **3.1's exemption strategy inverted.** The plan expected ~44 composition-root edges to be
   stated as `ignore_imports`, taking `import_exemptions` from 62 to ~106. Two things made that
   unnecessary: import-linter 2.13 accepts only exact module pairs (a `di.* -> infrastructure.*`
   wildcard matched nothing), and enumerating 42 edges to say "the composition root is the
   composition root" is the noise the ratchet exists to prevent. The contract is scoped instead,
   with a meta-test closing the gap that scoping opens. **`import_exemptions` stayed at 62** --
   this plan moved no ceiling except `bare_env_reads`.
3. **The 4 edges were fixed rather than excused.** `semantic_skill_retriever` no longer defaults
   to `NumpyVectorStore` (the composition root passes it); `clawhub_importer` no longer defaults
   to `ClawHubGitAdapter`; and the three TYPE_CHECKING annotations now name ports --
   `SkillStorePort`, `VectorStorePort` (both existing), plus **two new ports**,
   `StrategyStorePort` and `ClawHubAdapterPort`, which the two adapters now explicitly implement.
   The fourth was `multi_source_research`'s `service_registry` parameter: nothing ever read it,
   so it was deleted with its attribute and docstring line rather than given a port.
4. **2.1's `close()` lives in `CompletedState`, not `PlanActFlow`.** The plan's sequencing note
   said the flow owns the session. `plan_act_flow.py` is at **exactly** its 1000-line allowlist
   limit, so any addition there trips `test_god_modules_under_800_lines` -- which it did, on the
   first attempt. `CompletedState` is where the terminal status is set, so the lifecycle reads
   better there anyway; that required one entry in the flow-states allowlist
   (`weebot.application.agents.executor._session_scope`, a state-holder, not an agent call).
5. **E1 was not implemented, on purpose.** The plan said to pass an explicit `max_tokens` at the
   cascade's two `self._llm.chat` sites instead of relying on the adapters' defaults. Those
   defaults differ by provider -- 16384 in `openai_adapter.py:161`, 4096 in
   `anthropic_adapter.py:64` -- and the repo's named constants are smaller still
   (`MAX_TOKENS_EXTENDED = 2048`). Picking one number therefore either cuts the OpenAI path by
   8x or raises the Anthropic path by 4x: a spend/truncation decision, not a refactor. E2 is
   implemented instead, and E1 belongs in a decision with a measured per-tier budget.

### The bug 4.0 found on its first run

`ExecutingState.execute`'s "all models are circuit-broken" branch read the *raw dicts* from the
command result with `getattr(e, "error", "")`, which returns `""` for a dict -- so `_all_tripped`
was always `False` and the branch was dead. Every cascade exhaustion therefore fell through to
the 3-tier routing and replanned against a cascade with nothing left in it. Twelve lines below,
a comment records the identical defect for `_error_msg` ("an isinstance check never matches a
dict, so every failure read as 'step execution failed'"); that one was fixed, this one was not.
It now reads the reconstructed events, and the scripted test asserts the UNVERIFIED outcome and
that no second attempt is made.

### Gates run after the change

| Gate | Result |
|---|---|
| `pytest tests/unit` | **6280 passed**, 102 skipped, 3 xfailed, **5 failed** -- all 5 fail identically at `b9c4c378` (2 `test_candidate_inventory`, 2 `test_w7_connection_lifecycle`, 1 `test_child_process_and_browser_teardown`). Two further HEAD-only failures are now green: `test_map_is_consistent::test_the_tasks_index_is_the_generated_one` (WB-10) and `test_verified_cards_cite_real_files_and_lines` (cards updated for the moved lines). |
| `lint-imports` | 11 contracts, **11 kept, 0 broken** (was 10). |
| `test_architecture_fitness.py` | 64 passed, **0 skipped** (was 62 / 1). |
| Ratchets | `module_cycles 0`, `unresolved_di_keys 0`, `unregistered_di_keys 0`, `string_di_keys 44`, `import_exemptions 62`, `dynamic_weebot_imports 15`, `silent_except_handlers 112`, `blocking_io_in_async 0`, `unawaited 0`, `functions_over_150_lines 28`, `settings_construction 0`, `container_construction 7` -- all unchanged. `bare_env_reads 68` (lowered, ceiling moved). |
| `ruff_violations` | **741, at its ceiling** (was 743). The audit read this as a tool-version artifact; that was wrong. Running at `e72f5126` — the commit that *introduced* the 741 ceiling — measures **743**, so the ceiling was recorded before its two fixes were counted and the gate had been red since the day it was added. The two were paid in `cli/commands/flow.py`'s `decisions` panel (two E501 lines, now wrapped), `web/auth.py` itself being clean. `ruff` is pinned to `==0.17.2` in `requirements.txt` in the same change, because an exact-count ceiling cannot depend on a floating tool version. No ceiling moved. |
| Map / index | Initially reported green because I ran `check_map_citations.py` without `--drift`, the flag `make lint-map` actually uses. With it: **155 citations were already drifted on `b9c4c378`** and 202 on this branch, so the gate had been red on `main` too. `--fix` relocated the shifts and demoted the 8 cards whose cited text was already gone (`DIContainer`, `PlanActFlow`, `Browser`, `LLMAdapters`, `CLI`, `WebUI`, `BrowserTools`, `IntegrationTools`) to `status: stale` -- honest, where they had been silently wrong. The 2 cards my own change made stale (`SkillRegistry`, `BuiltinSkills`, both citing `di/_skills.py` where the store is now constructed) were re-read against source and re-verified by hand. `map/objects/_index.md` regenerated. Final: 0 broken, 0 drifted. |

### Not done, and why

- **Phase 5 (WB-07)**: still owned by the 2026-09 plan's Phase 5, as decided. 2.1 removed its
  prerequisite blocker for 5.4 (the taint cache is no longer process-global-by-accident but
  process-global-by-owner, with a lifecycle).
- **E1 (`max_tokens` at the cascade)** and **E3 (a cost-dashboard record for saturation)** and
  **E4 (provider idempotency keys)**: see deviation 5 for E1. E3 would publish a zero-token
  record for a call that never happened; E4 needs a provider that supports the key. Both are
  optimisations with no defect behind them, and this plan's ledger is closed.
- **`PlanActFlow.__init__` (234 lines) was not turned into `from_config()`.** It is 4.2 step 1 in
  the plan above; the two named targets of 4.2 (execute_step, `_base.py`) are met, and the flow
  constructor is the one place every test constructs, so it deserves its own change rather than
  the tail of this one.
- **The 5 pre-existing unit failures** above: they predate this work and are not in this
  plan's ledger. They belong in a defect-hunt candidate, not here.
- **Two more gates were red on `main` and are now green**, both found by CI rather than by me:
  the `ruff_violations` ceiling (above), and `make lint-map` (155 drifted citations). The
  lesson recorded here because it will recur: I ran `check_map_citations.py` and read its
  "0 broken" as the gate passing, when the gate is `--drift`; and I reported `ruff_violations`
  as a tool-version artifact without measuring at the commit that set the ceiling. Both were
  caused by trusting a proxy for the real command.
- **8 map cards are now `stale`** rather than silently `verified`: their cited text was already
  gone at `b9c4c378`. Re-verifying them needs a human re-read against source (map/_meta/schema.md),
  which is not this plan's work and was not faked.


