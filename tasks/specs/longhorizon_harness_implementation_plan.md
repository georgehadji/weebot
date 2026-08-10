# LongHorizon-Harness → weebot: implementation plan

**Source analysis:** [`tasks/specs/longhorizon_harness_weebot_analysis.md`](longhorizon_harness_weebot_analysis.md) — read that first for the paper summary and full gap evidence. This file is the actionable subset: what to build, in what order, in which layer, with what to watch for.

**Core finding:** weebot has no independent completion authority. The executor marks its own steps COMPLETED ([`executor/_base.py:951`](weebot/application/agents/executor/_base.py:951)); verification runs once, terminally, after everything is already marked complete, and reads the executor's own claims as evidence ([`verifying.py:583`](weebot/application/flows/states/verifying.py:583)); two gates fail open ([`verifying.py:232`](weebot/application/flows/states/verifying.py:232), [`:639`](weebot/application/flows/states/verifying.py:639)).

**The non-obvious part:** the fix is mostly wiring, not new subsystems. `_gate_artifact_verification` ([`verifying.py:432`](weebot/application/flows/states/verifying.py:432)) already does real environment-grounded checks. `TaskRoute`/`TaskPreset` already exist end to end but are never wired together. Both need extraction into the right layer before they can carry weight — see the constraints below.

---

## 0. Architecture constraints

Stated once so each item below can stay short. Every one of these is a rule weebot already declares and the current code already breaks in the exact places this plan touches.

**C1 — No filesystem access from the Application layer.** [`FileStoragePort`](weebot/application/ports/file_storage_port.py) says it outright: *"Application-layer services MUST NOT use `open()` or `os.path` directly."* `_gate_artifact_verification` does `from pathlib import Path`, `Path(p).exists()`, `Path(out_path).stat()`, and a bare `open(out_path)` — three violations, inside a flow state. It is tolerable today because the gate is advisory. E1 makes it load-bearing, at which point it must go behind the port.

**C2 — Dependencies point inward: Interfaces → Infrastructure → Application → Domain.** Policy decisions belong inward, not in `interfaces/factories.py`. Domain stays pure (stdlib + pydantic only).

**C3 — Domain types, not strings.** `_gate_artifact_verification` returns `list[str]` with values like `f"image_svg_disguised:{out_path}"` — structured data encoded into strings. [`weebot/domain/models/audit.py`](weebot/domain/models/audit.py) already defines `AuditReport`, `Violation`, `ViolationSeverity`, `AuditVerdict` and is already the right shape. Reuse it; do not invent a parallel result type.

**C4 — Immutability.** `Step`/`Plan`/`Session` are all `model_copy`-based. New fields use `Field(default_factory=...)` and are replaced, never mutated in place.

**C5 — Ports for anything crossing a boundary; register in DI.** `AuditService` is already registered at `di/_factories.py:95`. New services follow the same path so they are injectable and testable without a live flow.

**C6 — Do not add modules under `weebot/application/harness/`.** That is the *benchmark* harness (`BenchmarkRunner`/`TaskLoader`/`TaskScorer`), unrelated to MEA. Name collision.

---

## Sequencing

```
E2 (domain model)
  └─→ E1 (gate = Tier 0, extract + reuse existing checks)
        └─→ E4 (fail closed)
              └─→ E3 (fact provenance)
                    └─→ E5/E6 (depth gating + cost tuning)
                          └─→ E7 (only if E1 grows tools)
```

E1 needs E2's acceptance criteria to check against. E4 is only meaningful once a real gate exists behind it. E6 is tuning that should follow a working gate.

**Exception:** E5's wiring half is ~15 lines, independent of everything else, and can land anytime — but it only buys anything once Tier 1 exists (needs E2). Don't pull it earlier just because it's easy.

---

## E1 — Extract the artifact gates into a service; make them the completion authority

**★ highest value — do this first**

**Change:** before [`executing.py:512`](weebot/application/flows/states/executing.py:512) marks a step `COMPLETED`, run the environment-grounded checks currently in `_gate_artifact_verification`, scoped to *this step's* `ToolEvent`s (`_current_step_events`, already assembled at [`executing.py:472`](weebot/application/flows/states/executing.py:472)). Failure ⇒ the step does not become `COMPLETED`.

**Why first:** reuses code that already exists and already reads the environment. No new agent, no model calls, no token cost. Converts weebot's strongest existing verification asset from a terminal report into a gate.

### Architecture

Do **not** copy the method into `ExecutingState` — that duplicates 110 lines across two states and leaves C1 broken in both. Extract once:

| Layer | Artifact |
|---|---|
| Domain | reuse [`AuditReport`](weebot/domain/models/audit.py) / `Violation` / `AuditVerdict` as the return type (C3) |
| Application — port | `StepAuditPort.audit_step(step, events, session_id) -> AuditReport` |
| Application — service | `StepEvidenceAuditor(StepAuditPort)` — the three gates, taking `FileStoragePort` by constructor injection (C1, C5) |
| Infrastructure | existing `FileStoragePort` adapter; **add `size(path) -> int | None`** — the port has `exists()` but Gate C needs file size, which is why the current code reaches for `Path.stat()` |
| Callers | `ExecutingState` (per-step, new) and `VerifyingState` (terminal, replacing the inline method) both call the port — one source of truth |

Name it `StepEvidenceAuditor`, not `AuditService` (taken, and that one is regex-over-strings) and not anything under `harness/` (C6).

**Paradigm note — deliberately not abstracting.** Three gates (files-exist, test-output, image-quality) stay as three private methods on one service. A rule-object registry or Strategy hierarchy for three items is the over-engineering this codebase already has too much of. Revisit only if a fourth and fifth gate arrive.

**Watch:** `_all_tripped` at [`executing.py:415`](weebot/application/flows/states/executing.py:415) force-marks `COMPLETED` when all models are circuit-broken. That path must set `UNVERIFIED` (E2) instead, or it silently bypasses the new gate.

---

## E2 — Add `UNVERIFIED` status and acceptance criteria to `Step`

**Change** (all in [`weebot/domain/models/plan.py`](weebot/domain/models/plan.py), pure domain):

```python
class StepStatus(str, Enum):
    ...
    UNVERIFIED = "unverified"      # executed, evidence did not support completion

class Step(BaseModel):
    ...
    acceptance_criteria: list[str] = Field(default_factory=list)   # paper's contract cᵢ
    evidence_refs: list[str] = Field(default_factory=list)

    def mark_unverified(self, reason: str) -> "Step": ...           # sibling of mark_completed
```

`PlannerAgent` emits `acceptance_criteria` per step. Keep it inside the existing structured-output Pydantic contract — do not add a second parse path.

**Why:** without a per-step acceptance criterion there is nothing for E1 to check *against*. "The file exists" is presence; the paper's clearest empirical lesson is that presence ≠ validity.

### Two domain bugs this will introduce if not handled

**1. `Plan.merge()` silently drops unverified steps.** [`plan.py:141`](weebot/domain/models/plan.py:141) keeps `[s for s in self.steps if s.is_done()]` and refills the rest from the updated plan. An `UNVERIFIED` step is not done, so it is dropped from `completed` — and it only survives if the planner happens to re-emit it. Fix inside the domain model, not at the call site:

```python
retained = [s for s in self.steps if s.is_done() or s.status is StepStatus.UNVERIFIED]
```

**2. `Plan.get_next_step()` will re-execute it forever.** [`plan.py:102`](weebot/domain/models/plan.py:102) returns the first not-done step, so an `UNVERIFIED` step is picked up again immediately. Bound it with the **existing** `Step.retry_count` (already capped at 1 by the step validator at [`executing.py:465`](weebot/application/flows/states/executing.py:465)) — do not add a second counter for the same concept.

**Cost / risk:** touches `plan.py`, the planner, and every `is_done()` caller. **Grep all callers before changing.** This is precisely the shared-behavior change class that the `verify-scope-lesson` memory exists for — a subset check gave false confidence last time.

---

## E3 — Give session facts provenance and a trust level

**Change:** facts currently land as a bare `dict[str, Any]` ([`session.py:40`](weebot/domain/models/session.py:40)) via `set_fact(key, value)` ([`:282`](weebot/domain/models/session.py:282)), straight from executor extraction at [`executing.py:527`](weebot/application/flows/states/executing.py:527) — no provenance, no trust level. An unverified claim becomes a durable premise.

### Architecture

**Do not add a parallel `fact_sources` dict.** `_cap_facts_dict` ([`session.py:61`](weebot/domain/models/session.py:61)) FIFO-evicts at 100 entries; a second dict would desync on eviction and leave facts with dangling or wrong provenance. Use a value object as the dict *value*:

```python
# weebot/domain/models/session.py — frozen, pure domain (C4)
class FactSource(str, Enum):
    EXECUTOR = "executor"   # claimed, unverified
    AUDIT = "audit"         # environment-confirmed
    USER = "user"           # asserted by the operator

class Fact(BaseModel):
    model_config = ConfigDict(frozen=True)
    value: Any
    source: FactSource = FactSource.EXECUTOR
    verified_by: str | None = None    # audit report id
```

`set_fact(key, value, *, source=FactSource.EXECUTOR, verified_by=None)` — keyword-only so every existing call site keeps working unchanged.

**Watch:** `get_fact()`/`get_facts()` must unwrap `Fact.value` or every existing reader breaks. Serialization at [`session.py:82`](weebot/domain/models/session.py:82) (`"facts"` in the persisted context) and `:300` need a migration path for already-stored sessions — a plain value read back from SQLite is a legacy `EXECUTOR` fact. Grep all callers (C4, verify-scope-lesson).

Planner/executor prompt rendering marks `source != AUDIT` as explicitly unverified. That render change is where the paper's actual benefit lands — the storage change alone does nothing.

---

## E4 — Make the verification gates fail closed

**Change:** [`verifying.py:639`](weebot/application/flows/states/verifying.py:639) and [`:232`](weebot/application/flows/states/verifying.py:232) must not return a passing value on exception.

**Architecture:** `verification_status: "not_run"` is another stringly-typed field (C3). Put the enum next to the other audit types in [`domain/models/audit.py`](weebot/domain/models/audit.py):

```python
class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"     # gate raised — distinct from, and never equal to, PASSED
```

Surface it in the completion stamp.

**Why:** a not-run gate currently reads as a passed gate. The existing warning log at `:232` already admits this is a problem; only the behavior was never changed.

**Note:** will surface real failures currently swallowed. Expect noise on first run — stage it after E1 so there's a real gate behind it, not before.

---

## E5 — Gate verification *depth*, not verification itself

**Why gating is required at all:** the paper's own data — hard tasks +0.122 vs medium +0.042 (Table 10); regressions concentrated in data-science, mathematics, mteb, video-processing (Tables 9, 11); auditing costs 19–38% of tokens. Universal MEA would make weebot *worse* on short analytical tasks while costing more.

**The discriminant is not task complexity.** The tasks that regress (math, data-science, mteb, video) share no durable external state. The tasks that gain (files, terminal, GUI) mutate an environment. So gate on **does this step leave evidence outside the model's own text** — per-step, derivable from `ToolEvent`s with zero model calls, self-selecting.

Do not use [`_estimate_complexity`](weebot/application/services/keyword_task_router.py:121) as the predicate — it is keyword matching and gets the regressing category backwards (`"create a summary of this data"` hits `"create"` → `HIGH`).

**Depth ladder:**

| Tier | Trigger | Cost | What runs |
|---|---|---|---|
| 0 | step has environment-touching `ToolEvent`s | 0 tokens | mechanical checks — this *is* E1 |
| 1 | Tier 0 found evidence, can't judge acceptance | 1 cheap-model call | evidence vs. `Step.acceptance_criteria` (needs E2) |
| 2 | preset is `complex` **and** Tier 1 says `needs_revision` | full audit + replan | the paper's actual MEA round |

Tier 0 is free → universal. The 19–38% overhead is entirely Tiers 1–2 → that's what the preset gates.

### Architecture

The dial is dead today (analysis §3.7): `route_and_create_flow` computes `TaskRoute(category, complexity)` on every query ([`factories.py:89`](weebot/interfaces/factories.py:89)) but `create_flow` reads only `.flow_type` ([`:142`](weebot/interfaces/factories.py:142)); `get_preset()` has zero production callers.

**Route→preset mapping is policy — it does not belong in `interfaces/` (C2).** Put a pure function beside the registry, which already imports the domain model:

```python
# weebot/config/task_preset_registry.py
def select_preset(route: TaskRoute) -> TaskPreset:
    if route.complexity is TaskComplexity.LOW:
        return PRESET_SIMPLE
    if route.category is TaskCategory.COMPLEX:
        return PRESET_COMPLEX
    return PRESET_STANDARD
```

`factories.py` then just calls `select_preset(task_route)` and threads `task_preset=` through `PlanActFlow.__init__` into `PlanActFlowConfig`. Unit-testable without constructing a flow.

**Depth is an enum, not a magic int (C3).** In [`task_preset.py`](weebot/domain/models/task_preset.py) — `IntEnum` is stdlib, so the domain stays pure:

```python
class AuditDepth(IntEnum):
    EVIDENCE_ONLY = 0
    ACCEPTANCE = 1
    FULL_AUDIT = 2

@dataclass(frozen=True)
class TaskPreset:
    ...
    audit_depth: AuditDepth = AuditDepth.ACCEPTANCE
```

`simple` → `EVIDENCE_ONLY`, `standard` → `ACCEPTANCE`, `complex` → `FULL_AUDIT`.

**Fix the config field type while here.** [`plan_act_flow_config.py:100`](weebot/application/models/plan_act_flow_config.py:100) is `task_preset: Any | None` commented *"avoids domain model import"* — but Application→Domain is the **correct** direction under C2, and the other `Any` fields on that class have real reasons (ports, templates layer). This one just loses type safety on a field about to become load-bearing. Type it `TaskPreset | None`.

**Watch:** this is the first time `_task_preset` is ever non-`None` in production. It also switches on `enable_premortem` for complex and `enable_step_validation=False` for simple — gates that have never fired. Land wiring + `audit_depth` in one commit; confirm `PRESET_SIMPLE.enable_step_validation=False` is actually wanted before shipping.

---

## E6 — Run verifier roles on a cheaper cascade tier

**Change:** per-role tier constants in `model_cascade_config.py`; verification-role calls enter the cascade at BUDGET, executor stays PREMIUM.

**Architecture:** configuration only — `CascadeExecutor.call_with_cascade()` is already the mandated path (CLAUDE.md rule 4) and already supports entry-tier selection. No new code. If it turns out to need code, that's a signal the tier constants are in the wrong place, not that a new selector is needed.

**Why:** the paper measures the manager role at 2.0–8.1% of tokens. Terminal-Bench was −24% tokens overall with the harness.

---

## E7 — Workspace snapshot guard

**Only if E1 grows into a tool-using verifier.** weebot's verifier has no tools today, so it cannot mutate anything — the guard is inert. The moment E1's checks move from reading events to running inspection commands, add snapshot-and-diff: mutation ⇒ integrity violation ⇒ audit cannot support completion.

**Architecture when that day comes:** snapshot/diff is filesystem work ⇒ Infrastructure adapter behind a port (C1), invoked as a context manager around the verification episode so restore-on-exit is structural rather than a `finally` someone forgets. Note that [`AuditDimension`](weebot/domain/models/audit.py:16) has no `INTEGRITY` member — the paper's second axis. Add it then, not now.

---

## Explicitly not recommended

**Fresh-context-per-round executors.** weebot already has `_step_budget`, `TrajectoryMonitor`, and context compaction guarding the flailing failure the paper dramatizes. The residual gap is *what* crosses the step boundary (unverified claims), not *how much context* — E3 fixes that directly, at far lower risk than restructuring the executor loop.

**Three-process role split.** LH-Harness spawns separate CLI episodes per role because it wraps opaque third-party tools it cannot instrument. weebot owns its executor and can enforce the same invariant in-process. Take the invariant — *executor claims never advance state* — not the process topology.

**A rule/strategy registry for the artifact gates.** Three gates, one service, three private methods. See E1.

---

## Validation

The honest test of E1–E4 is a regression fixture: a task where the executor *claims* success and the environment contradicts it (claims a file was written, file isn't there; claims tests pass, output has a failure marker). Home: `infrastructure/fixtures/regression/`.

Extracting the gates into `StepEvidenceAuditor` behind `FileStoragePort` (E1) is what makes this testable at all — an in-memory `FileStoragePort` fake lets the fixture assert gate behavior with no disk and no LLM. That is the practical payoff of C1, not just tidiness.

Without this fixture, none of E1–E4 is falsifiable — which is the exact failure mode the paper is about.
