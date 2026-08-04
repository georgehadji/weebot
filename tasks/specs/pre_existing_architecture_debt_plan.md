# Pre-Existing Architecture Debt — Remediation Plan

**Status:** proposed
**Date:** 2026-08-04
**Scope:** `weebot/application/cqrs/`, `weebot/application/services/task_runner.py`,
`weebot/domain/legacy_models.py`, dev tooling
**Not in scope:** the mission-center UI work (see
`mission_center_ui_implementation_plan.md`) — this plan covers debt that predates
that work and was surfaced while verifying it, not anything introduced by it.

---

## 0. How this was found

While closing out the mission-center UI implementation, the full backend regression
suite (`tests/unit/test_architecture_fitness.py`, 51 tests, ~5 min) was run for the
first time this session. It returned **50 passed, 1 failed, 1 skipped**. The failure
was investigated to confirm whether it was caused by this session's changes; it was
not (confirmed via `git show HEAD`, see RC-2 below). Investigating that failure
surfaced a second, larger, previously-undocumented issue (RC-1) that no existing
test catches.

This plan covers exactly what was found and verified — it is not a general codebase
audit. The codebase already tracks a substantial amount of *known, documented* debt
inside `test_architecture_fitness.py` itself (a god-module allowlist under "WP-2", an
orphan-ports allowlist with reasons) — that tracked debt is referenced for context
in §4 but is out of scope for this plan; it already has an owner (WP-2) and a test
keeping it honest.

---

## 1. Root-cause findings (verified against source)

| ID | Finding | Evidence | Impact |
|----|---------|----------|--------|
| **RC-1** | **8 CQRS handler modules are marked `DeprecationWarning: "Use direct service calls"` at import time, yet are the live, actively-registered production dispatch path** — not legacy code left over from a completed migration. | `weebot/application/cqrs/handlers/{update_plan_handler,cancel_session_handler,compact_memory_handler,summarize_handler,archive_session_handler,session_queries,plan_queries,active_queries}.py` each `warnings.warn(..., DeprecationWarning)` at module scope. All 8 are imported and registered by `register_default_handlers()` ([handlers/\_\_init\_\_.py:104-230](../../weebot/application/cqrs/handlers/__init__.py)), which is called from `Container._create_mediator` ([di/\_\_init\_\_.py:338](../../weebot/application/di/__init__.py)) — invoked on **every** `container.get(Mediator)`, which `build_chat_flow` and every mediator-aware `PlanActFlow` resolve on **every chat turn and every task run**. Concrete live call sites confirmed: `ops_router.py` dispatches `GetActiveSessionsQuery`/`GetPlanVisualizationQuery`/`GetCostSummaryQuery` (all "deprecated") on every Ops dashboard load ([ops_router.py:36,65,95](../../weebot/interfaces/web/routers/ops_router.py)); `flows/states/updating.py` dispatches `UpdatePlanCommand`; `flows/states/summarizing.py` dispatches `SummarizeCommand`. | Every server boot and most test collections currently print 7-8 `DeprecationWarning`s (already visible throughout this session's pytest output) for code with no completed migration path — the warning is aspirational, not actionable. A future maintainer reading the warning has no way to know these are load-bearing; "delete this deprecated code" is a plausible, wrong, production-breaking read of the current state. |
| **RC-2** | **Confirmed import-linter violation, pre-existing, not introduced this session.** `interfaces.web.routers.sessions` → `application.services.task_runner` → `application.services.metrics_bridge` → `infrastructure.observability.metrics` (violates "Interfaces must not depend on infrastructure directly"), and → `application.flows.plan_act_flow` → `application.flows.collaborators.tool_assembler` → `weebot.tools.tool_registry` (violates "Interfaces must not depend on weebot.tools directly"). | `lint-imports --config .importlinter --verbose` run directly, both chains reproduced. `git show HEAD:weebot/interfaces/web/routers/sessions.py` confirms `from weebot.application.services.task_runner import TaskRunner` already existed at lines 173 and 257 *before* this session's changes — this session's new `dispatch_session_input.py` merely adds a second path to an already-broken destination, it did not create the violation. | `test_architecture_fitness.py::test_core_no_application_imports` fails on every run. Root cause is structural: `TaskRunner` lives in `application/services/` (correctly) but itself reaches into `infrastructure/` (for metrics) and, via `PlanActFlow`, into `weebot/tools/` — so **any** file in `interfaces/` that imports `TaskRunner` transitively breaks the contract, regardless of how carefully that file itself respects layering. `sessions.py` has no way to stay compliant while using `TaskRunner` directly. |
| **RC-3** | **The B006 mutable-default-argument lint check silently no-ops in this environment.** | `test_no_b006_violations` ([test_architecture_fitness.py:1305-1330](../../weebot/../tests/unit/test_architecture_fitness.py)) does `ruff = shutil.which("ruff"); if ruff is None: pytest.skip(...)`. `ruff` is not on PATH in this dev environment — confirmed by the "1 skipped" in every fitness run this session. | A real code-quality gate (mutable default arguments — a classic Python footgun) has been silently inert for however long `ruff` has been missing from this environment's setup. Nobody currently sees this as a failure; they see a skip, which reads as "not applicable" rather than "not checked." |
| **RC-4** (minor, informational) | `weebot/domain/legacy_models.py` is deprecated with a documented migration table (Task→Step, Project→Session, etc.) but is still imported by `weebot/templates/agent_integration.py` and re-exported — with its own deprecation warning *suppressed* — by `weebot/domain/models/__init__.py`. | [legacy_models.py:1-30](../../weebot/domain/legacy_models.py), [domain/models/\_\_init\_\_.py:7-12](../../weebot/domain/models/__init__.py) suppresses `DeprecationWarning` via `warnings.simplefilter("ignore", ...)` before re-exporting. | Lower severity than RC-1: this one is honestly documented with a clear target and only one non-test consumer (a project-scaffold template, not the live web/CLI runtime). Included for completeness; not urgent. |

---

## 2. What NOT to do

- **Do not silence the RC-1 deprecation warnings without migrating.** Wrapping the
  imports in `warnings.catch_warnings()` or deleting the `warnings.warn()` calls
  would remove the visible symptom while leaving the actual architectural question
  (should this go through the mediator or not?) unanswered — worse than the current
  state, because it removes the only signal that anything is wrong.
- **Do not delete the "deprecated" handlers to make the warnings go away.** They are
  load-bearing (RC-1 evidence). Deleting them breaks Ops dashboard queries, plan
  updates, summarization, session cancel/archive/compact — a subset of which this
  session's mission-center UI now depends on (`/ops` page → `GetActiveSessionsQuery`
  etc.).
- **Do not try to make `TaskRunner` itself import-linter-compliant by moving it into
  `infrastructure/`.** `TaskRunner` is correctly an application-layer orchestration
  service (it has no adapter responsibilities) — the fix belongs at the port
  boundary (RC-2, Phase 2), not by relocating a correctly-placed class to satisfy a
  tool.

---

## 3. Phased plan

### Phase 1 — Resolve the CQRS deprecated-but-live contradiction (RC-1)

The 8 flagged handlers split cleanly into two groups by what they actually do —
verified by grep (`grep -L DeprecationWarning` across all handler files): the
**agent-calling / cross-cutting handlers** (`CreatePlanHandler`, `ExecuteStepHandler`,
`ProcessMessageHandler`, skill-edit/validation/transfer/trajectory/failure-signature
handlers) are **not** marked deprecated — they genuinely benefit from the mediator
(event fan-out, uniform command/result shape, pipeline hooks). Only the **simple
single-repository-call** handlers are flagged. That split is itself the evidence for
the right fix: finish what the deprecation notices already say.

**T1.1 — Enumerate every live call site per deprecated handler**
- Files: read-only research pass over `weebot/`
- For each of the 8 Commands/Queries (`UpdatePlanCommand`, `CancelSessionCommand`,
  `CompactMemoryCommand`, `SummarizeCommand`, `ArchiveSessionCommand`,
  `GetSessionQuery`, `GetSessionStatusQuery`, `ListSessionsQuery`,
  `GetSessionHistoryQuery`, `SearchSessionsQuery`, `GetSimilarSessionsQuery`,
  `GetPlanQuery`, `GetPlanVisualizationQuery`, `GetActiveTasksQuery`,
  `GetActiveSessionsQuery`, `GetCostSummaryQuery`), grep for `mediator.send(` /
  `mediator.query(` construction sites. Three are already confirmed
  (`ops_router.py`, `flows/states/updating.py`, `flows/states/summarizing.py`);
  the rest need the same treatment before Phase 1 continues, since a wrong call-site
  inventory here means broken queries later.
- Acceptance: a complete table (command/query → every call site → proposed direct
  replacement) checked into this plan or a follow-up doc before T1.2 starts.

**T1.2 — Replace call sites with direct service/repository calls, one handler at a time**
- Pattern per handler: the handler's `handle()` body is almost always already a
  thin wrapper over 1-2 `state_repo` calls (confirm per-handler, they were written
  as thin wrappers deliberately per their docstrings — "Split from
  weebot/application/cqrs/handlers.py during architecture remediation"). Replace
  `await mediator.send(XCommand(...))` at each call site with the equivalent direct
  `await state_repo.foo(...)` (or the 1-2 line service call the handler wraps).
- Do this **one handler at a time**, each as its own commit: replace call sites →
  delete the handler file and its Command/Query class → delete its
  `register_command_handler`/`register_query_handler` line in
  `handlers/__init__.py` → run the full test suite → commit. This keeps any
  regression bisectable to one handler.
- Order by call-site count, fewest first (lowest risk): `ArchiveSessionHandler` and
  `CancelSessionHandler` look like single-call-site candidates from T1.1; save
  `session_queries.py`/`plan_queries.py` (6 query classes each with more surface)
  for last.
- Acceptance per handler: its Command/Query class, handler file, and registration
  line are gone; `grep -r "XCommand\|XQuery"` returns nothing; all existing tests
  for the affected endpoint still pass with identical response shape.

**T1.3 — Remove the now-empty deprecation scaffolding**
- Once every handler in the group is migrated, `register_default_handlers()`
  shrinks to only the non-deprecated (agent-calling) handlers — verify by re-reading
  `handlers/__init__.py` that no `warnings.warn` import remains anywhere under
  `cqrs/handlers/`.
- Acceptance: `python -W error::DeprecationWarning -m pytest tests/unit -x` (turns
  warnings into errors) passes with zero `cqrs.handlers` warnings — this becomes the
  regression guard so this contradiction can't silently reappear.

### Phase 2 — Fix the confirmed import-linter violation (RC-2)

**T2.1 — Introduce a thin `TaskRunnerFacadePort` (or reuse an existing port) that `interfaces/` depends on instead of the concrete `TaskRunner`**
- The dependency-rule violation exists because `sessions.py` needs exactly three
  `TaskRunner` operations (`start_session`, `cancel_session`, and the
  `create_plan_act_factory` builder) but importing the *class* pulls in
  `TaskRunner`'s own transitive imports (metrics, tool_assembler → tools).
- Files: `weebot/application/ports/task_runner_port.py` (new, minimal Protocol with
  exactly the 2-3 methods `sessions.py` calls), `TaskRunner` gets registered under
  both its concrete type (existing callers) and the new port (for interfaces-layer
  resolution) via `container.get(TaskRunnerPort)`.
- Update `sessions.py` and `dispatch_session_input.py` (this session's new file) to
  import and depend on `TaskRunnerPort`, not `TaskRunner`.
- This mirrors the exact pattern already used successfully for `EventBusPort` /
  `EventPublisherPort` (interface segregation specifically to keep a narrow
  interfaces-layer dependency free of a wide concrete class's transitive imports) —
  same shape, same justification, already precedented in this codebase.
- Acceptance: `lint-imports --config .importlinter --verbose` reports `0 broken`
  contracts. `test_core_no_application_imports` passes.

**T2.2 — Guard against regression**
- No new test needed beyond the existing `test_core_no_application_imports` — it
  already catches this class of violation; it was just failing silently (as a
  "known failure" nobody was looking at, per this plan's own discovery process).
  Once T2.1 lands, its continued passing *is* the guard.

### Phase 3 — Close the tooling gap (RC-3)

**T3.1 — Install `ruff` in the dev/CI environment**
- Add `ruff` to `requirements.txt` (or dev-requirements) and document it in
  environment setup so `test_no_b006_violations` actually runs instead of skipping.
- Acceptance: `shutil.which("ruff")` resolves; the fitness suite's skip count drops
  from 1 to 0; if B006 violations exist in the codebase once the check actually
  runs, file them as a follow-up (out of scope to fix here — this phase is about
  making the gate live, not about whatever it then finds).

### Phase 4 — Deferred / low priority (RC-4)

- `weebot/templates/agent_integration.py`'s use of `legacy_models` is the last
  non-re-export consumer. Migrating it to the Pydantic v2 models per
  `legacy_models.py`'s own migration table is a clean, low-risk follow-up but has no
  urgency (single consumer, already documented, warning already suppressed at the
  re-export boundary so it causes no noise). Not scheduled in this plan; flagged for
  whoever next touches `templates/agent_integration.py`.

---

## 4. Explicitly out of scope (already tracked elsewhere)

- **WP-2 god-module decomposition** — `test_god_modules_under_800_lines`
  ([test_architecture_fitness.py:860-888](../../weebot/../tests/unit/test_architecture_fitness.py))
  already tracks `_catalog.py` (3900 lines, documented as regenerated data),
  `_base.py` (1450), `plan_act_flow.py` (1000), `information_synthesis.py` (900),
  and `model_selection.py` (100-line re-export shim) against a shrinking-target
  allowlist. This is a live initiative with its own test-enforced budget; this plan
  does not duplicate it.
- **Orphan ports allowlist** — `test_orphan_ports_flagged` already tracks ~25 ports
  whose implementations live outside the scan's search path (application/ services
  instead of infrastructure/), each with a documented reason. No new orphans were
  found during this investigation.

---

## 5. Testing strategy

| Layer | Check |
|---|---|
| Regression guard (already exists) | `pytest tests/unit/test_architecture_fitness.py -v` — must reach 51 passed / 0 failed / 0 skipped after Phases 1-3 (currently 50/1/1) |
| Phase 1 per-handler | Existing endpoint tests for whatever route dispatches that Command/Query (e.g. `/api/ops/*` for the Ops queries) — response shape must be byte-identical before/after |
| Phase 1 completion | `python -W error::DeprecationWarning -m pytest tests/unit -x` — zero `cqrs.handlers` warnings anywhere |
| Phase 2 | `lint-imports --config .importlinter --verbose` → `0 broken`; `test_core_no_application_imports` passes |
| Phase 3 | `shutil.which("ruff")` non-None; fitness suite skip count → 0 |

## 6. Risks & rollback

| Risk | Mitigation |
|---|---|
| A call site missed in T1.1's inventory silently breaks after its handler is deleted in T1.2 | One handler migrated + deleted per commit, full test suite run before each commit — a miss surfaces immediately and bisects to exactly one handler |
| `TaskRunnerPort` (T2.1) ends up needing more methods than initially scoped, growing back toward the full `TaskRunner` surface | Keep the port to exactly what `interfaces/` calls today (audit via grep, same as T1.1's approach) — if a future feature needs more, widen the port deliberately, don't pre-widen speculatively (YAGNI) |
| Installing `ruff` (T3.1) surfaces a backlog of B006 violations across the codebase | Explicitly out of scope for this phase (see T3.1 acceptance) — file as a separate follow-up so it doesn't block closing the tooling gap itself |

Rollback: each phase is independent and additive/subtractive in isolation — Phase 1
is a sequence of single-handler commits, each independently revertible; Phase 2 adds
one new port file and changes two import lines; Phase 3 is a dependency addition.
None touch the mission-center UI work.
