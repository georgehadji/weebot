# Bilevel Autoresearch → weebot: Implementation Plan

**Source paper:** Qu & Lu, *Bilevel Autoresearch: Meta-Autoresearching Itself*, arXiv:2603.23420v2
**Companion analysis:** [bilevel_autoresearch_weebot_analysis.md](bilevel_autoresearch_weebot_analysis.md)
**Baseline:** weebot @ `c6046fc` · drafted 2026-08-03
**Status:** Phase 0 and Phase 1 implemented in `74449bc`. Phases 2–4 not started.

---

## Part I — The paper

### I.1 Philosophy

The paper's claim is a *level* claim, not a technique claim.

An autoresearch loop is a search procedure. Every such loop embeds three separable things:

1. **the artifact** being optimized (a config, a skill document, a prompt),
2. **the parameters** of the search (which dimensions are live, how much budget, what guidance),
3. **the mechanism** of the search (how a proposal is generated, how it is accepted, what state
   carries between iterations).

Nearly all agent self-improvement work — weebot's included — operates on (1) and (2). The paper's
position is that (3) is a distinct and more powerful intervention surface, and that an LLM can
modify it autonomously by reading the loop's own source, diagnosing its failure mode, and writing a
replacement.

The second philosophical move is **carrier-independence**. Python code is used because it is
explicit, executable, and cheap to validate before activation — not because code is privileged. The
paper states directly that skills, prompts, workflows, evaluators, domain principles, world-model
assumptions, and memory schemas are all valid carriers of a mechanism, provided they change *how
future improvements are generated* rather than *which artifact is used this episode*. **This is the
clause that makes the paper applicable to weebot without adopting its risk profile.**

### I.2 Methodology

| Level | Optimizes | Cadence | Implementation |
|---|---|---|---|
| **1** | task output | every iteration | propose → train (300s) → eval `val_bpb` → keep if better |
| **1.5** | parameters of the mechanism | every 5 iterations | freeze params proposed ≥3× with no gain; unfreeze stale; inject guidance string |
| **2** | structure of the mechanism | every 2 outer cycles | 4-call dialogue → new Python operator → patch `runner.py` → validate → inject |

Level 2's dialogue is deliberately staged, one LLM call each:

1. **Explore** — read `runner.py` + full trace; survey adjacent fields (combinatorial optimization,
   online learning, DOE, Bayesian optimization); propose candidates.
2. **Critique** — score candidates against the *observed* failure mode; select one.
3. **Specify** — write the interface: class name, constructor args, method signatures, integration
   points.
4. **Generate** — emit runnable code plus the call-site changes.

Then: `importlib` load as the validation gate; on ImportError, restore from a pre-patch backup.

Ablation is a clean 2×2 over the two outer levels (A = L1, B = L1+1.5, C = L1+1.5+2, D = L1+2), all
other variables pinned (same model, same GPU, same 300s train budget, same 30-iteration search
budget, same baseline), 3 repeats each, metric Δ = best − baseline.

### I.3 Outcomes

| Group | Levels | Mean Δ val_bpb |
|---|---|---|
| A | 1 | −0.009 ± 0.002 |
| B | 1 + 1.5 | −0.006 ± 0.006 |
| C | 1 + 1.5 + 2 | **−0.045 ± 0.030** |
| D | 1 + 2 | −0.034 ± 0.031 |

Four outcomes matter downstream:

**(a) Level 1.5 did not pay, and actively hurt.** Group B is numerically *worse* than bare Group A.
The mechanism of harm is specific and instructive: the LLM's prior says "bigger batch is better", so
it proposed a `TOTAL_BATCH_SIZE` *increase* first; that failed; Level 1.5's freeze rule then locked
the parameter — permanently blocking the *decrease* direction, which was the single largest win
available (−0.039 to −0.065, 5–8× any other edit). **A parameter-level outer loop concluded "this
dimension is exhausted" when it had only tested one of its two directions.**

**(b) Level 2's gain came from breaking repetition, not from cleverness.** Group A's three repeats
followed nearly identical proposal sequences and accumulated up to **22 consecutive discards** out
of 30 iterations. All three generated mechanisms — Tabu Search, Multi-Scale Bandit, Systematic
Orthogonal Exploration — attack that one pathology from different angles. The lesson is that the
binding constraint was *the LLM re-proposing what it had already tried*.

**(c) Code generation was not the bottleneck.** Six sessions, six first-attempt successes, zero
retries. Five of six passed import validation; the sixth was valid code that needed an uninstalled
`sklearn`. The hard part is knowing *what* mechanism to write, not writing it.

**(d) The reported failure mode is silent fallback.** A preliminary run was invalidated by a
`sys.modules` registration bug that made every injection silently revert to the original runner. The
paper flags this explicitly as a dangerous failure mode. It is the same defect class documented in
§II.3 below, already present in weebot in two places.

### I.4 What the paper does *not* establish

- n=3, σ ≈ 67% of the mean, one benchmark, one model, one GPU. The 5× is directional.
- Group D's mechanism patches were **not successfully applied**, so it is not a clean ablation of
  "Level 2 without Level 1.5".
- Recursive self-application (Level 2 improving Level 2) is proposed, not demonstrated.
- No stability or convergence guarantee. No constraint on what the generated code may import.
- The Level 2 prompt names its candidate domains, so the discovered mechanisms are drawn from a
  human-anticipated set. Unprompted discovery is untested.

---

## Part II — weebot as it actually is

Established by reading source and by runtime probe, not by grep or docstring.

### II.1 Level mapping

| Paper level | weebot | Verdict |
|---|---|---|
| L1 | `SkillOptFlow` — rollout → reflect(failure/success) → merge → rank+clip → apply → validate gate → accept/reject → slow update → meta-skill | Designed richer than the paper's: evaluator co-evolution, adversarial pool, selective erasure, Thompson-sampled archive search. **Unreachable — see II.2.** |
| L1.5 | `slow_update`, `meta_skill`, `EvolutionTracker` narrative, `_build_evolution_context` (last 5 epochs), `SelfImprover` on contract YAML / rule MD | Present. All of it is "more text into an unchanged loop" — precisely Group B's shape. |
| L2 | — | Absent. |

weebot's `ThompsonSampler` archive search is a bandit over skill variants: weebot already ships,
hand-written, one of the three mechanisms Level 2 discovered on its own. That is the paper's point
about prior systems restated — good mechanisms, chosen by humans, fixed at design time.

`MetaSelfImprover` resembles L2 but is not: it reviews whether a *strategy string* should be
rewritten. That is L1.5 with extra steps.

### II.2 Blocking defect — the SkillOpt subsystem cannot be constructed

[`_skillopt.py:83`](../../weebot/application/di/_skillopt.py:83) calls `SkillOptFlow(...)` with
keyword arguments that do not match
[`skill_opt_flow.py:46`](../../weebot/application/flows/skill_opt_flow.py:46).

```
UNEXPECTED kwargs passed by DI : ['optimizer_llm', 'scorer', 'target_factory']
REQUIRED params DI never passes: ['event_bus', 'optimizer', 'target_flow_factory']
```

Runtime confirmation:

```
TypeError: SkillOptFlow.__init__() got an unexpected keyword argument 'optimizer_llm'
```

Python raises on the unexpected keyword before any constructor body executes, so there is no input
under which this succeeds. Both live entry points are dead: [`run.py:277`](../../run.py:277) and
[`cli/commands/flow.py:216`](../../cli/commands/flow.py:216).

Consequence: **every capability listed in the L1 row above is unexecuted code.** Evaluator
co-evolution, adversarial pool, selective erasure, archive search, evolution tracking, and the
epoch-boundary slow update have never run through this path. This is the single highest-value fix in
this document, and it precedes everything else — no measurement of weebot's optimization loop means
anything until the loop can be built.

It also confirms the standing conclusion recorded in the Hermes v0.19 study: weebot's binding
constraint is dead and unwired code, not missing capability.

### II.3 Silent no-op — `_run_self_improvement`

[`skill_opt_flow.py:576`](../../weebot/application/flows/skill_opt_flow.py:576) and `:600` build the
patch context as:

```python
"current_content": current,
"new_content": current,  # No change unless optimizer proposes one
```

[`self_improver.py:110`](../../weebot/application/services/self_improver.py:110) then:

```python
if current_content == new_content:
    logger.info("No change detected — skipping patch")
    return None
```

`new_content` *is* `current`. Every contract YAML and every rule MD returns `None`, every epoch,
forever. Logged at INFO, so a run looks healthy.

Root cause: **`SelfImprover` has no proposer.** `propose_patch` only diffs two strings handed to it;
nothing in the repo generates the second string. The trailing comment describes a call that does not
exist.

Two further layers: `self_improve_contracts` defaults `False` and no caller passes `True`;
`MetaSelfImprover` has zero constructor call sites repo-wide.

### II.4 Rejection amnesia

`_build_evolution_context` gives the optimizer the last 5 epoch *narratives* — scores and counts. It
has **no record of which edits were rejected**. Worse, the rejection event is emitted with the edit
stripped:

```python
yield SkillEditRejected(..., edit=None, failure_analysis=result.error or "Validation gate rejected")
```

The `SkillEditApplied` model already carries `accepted: bool` and `score_delta` — the domain shape
exists; nothing persists it. So weebot's optimizer is structurally free to re-propose a rejected
edit indefinitely. That is Group A's exact pathology, and weebot has no defence against it.

---

## Part III — What to take, what to refuse

### Take: the prioritization signal (free)

Two standing weebot recommendations are L1.5-shaped — richer context into an unchanged
proposal/accept mechanism:

- feed the misalignment journal into the Evolution Agent (Code-as-Harness analysis)
- close the live experience → skill loop (Memento analysis)

Group B is the first external evidence bearing on that shape, and it is negative. This does not
cancel either item. It changes their status from "expected win" to "must be measured", and it means
neither should be sequenced ahead of §IV Phase 0–2.

### Take: the diagnosis, which is cheap to act on

The 5× came from *stop re-proposing what you already tried*. weebot cannot do that today (II.4).
Fixing it needs no code generation, no runtime injection, no new subsystem.

### Take: the negative result about freezing

Level 1.5 froze a parameter after testing one of its two directions. Any weebot mechanism that
concludes "dimension exhausted" must record *which direction* was tried. This is a design constraint
on Phase 2, written into the tabu key.

### Refuse: runtime Python injection

Level 2's carrier is LLM-authored self-patching of the live runner. Against weebot that means write
access to `application/flows/`. `SelfImprover`'s allowlist deliberately refuses `.py` outside a
flag-gated two-file tier; that restraint is correct and stays. The paper's own limitations —
no stability guarantee, unconstrained imports, and a silent-fallback loader bug that voided a whole
run — do not justify the exposure at n=3 on one benchmark.

The paper explicitly says code is one carrier among many. weebot already owns safer carriers with
validation and rollback. **Phase 3 below takes Level 2's structural benefit through a Strategy
registry the LLM selects and configures, rather than code it writes.** That is the load-bearing
design decision in this plan.

---

## Part IV — Implementation plan

Architectural rules honoured throughout: dependencies point inward
(`interfaces → infrastructure → application → domain`); domain stays pure and I/O-free; application
imports infrastructure only inside function bodies; all agent output is Pydantic-validated; new
ports get adapters registered in DI or are listed as known orphans in the fitness test.

Phases are strictly ordered. Phase 0 gates every later phase.

---

### Phase 0 — Restore reachability (blocking, ~1 day) — **DONE (`74449bc`)**

**Problem:** II.2. `SkillOptFlow` and its DI call site drifted apart; a 24-parameter keyword
constructor made the drift invisible until runtime, and no test constructs the flow.

**Paradigm:** *Parameter Object* / *Whole Value*, with an immutable configuration DTO. This is not a
novel choice — weebot already does exactly this for the sibling flow
(`PlanActFlowConfig`, consumed at [`_skillopt.py:159`](../../weebot/application/di/_skillopt.py:159)).
Phase 0 makes `SkillOptFlow` consistent with the codebase's own established pattern.

| Step | Change | Layer |
|---|---|---|
| 0.1 | *Deferred.* The bug was fixed by correcting the call site (smaller, and it is the drift-detecting test that actually prevents recurrence). The Parameter Object remains the right refactor and is still open. New `SkillOptFlowConfig` — frozen Pydantic model, one field per current constructor parameter, validators for the co-required pairs (`use_archive_search` ⇒ `thompson_sampler`; `evaluator_slot` ⇒ `evaluator_selector`) | `application/models/` |
| 0.2 | `SkillOptFlow.__init__(self, cfg: SkillOptFlowConfig)`; body reads `cfg.*`. No behavioural change | `application/flows/` |
| 0.3 | `build_skill_opt_flow` constructs the config, then the flow. Rename drift dies here: `optimizer_llm` → the flow needs `optimizer` (the `OptimizerPort`, already available as `self.get(OptimizerPort)`), `target_factory` → `target_flow_factory`, `scorer` → dropped or added to the config as an explicit field, `event_bus` → `self._maybe_get(EventBusPort)` | `application/di/` |
| 0.4 | Regression test: build the flow through the real container with an in-memory DB and assert an instance comes back. This is the test whose absence allowed the drift | `tests/unit/` |
| 0.5 | Generalise 0.4 — a fitness test that every `build_*_flow` on the container is invocable with minimal arguments | `tests/unit/test_architecture_fitness.py` |

**Decision required at 0.3:** `scorer` is passed by DI and unknown to the flow, while `OptimizerPort`
is required by the flow and never passed. Determine from `_create_scorer` and the validation-gate
wiring whether the flow needs both or whether `scorer` is a leftover; do not paper over it by adding
an unused field.

**Acceptance:** `python -m cli.main flow ...` reaches `SkillOptFlow.run`; 0.4 and 0.5 pass; no
behavioural diff in the flow body (verify by diffing `cfg.x` substitutions only).

**Risk:** low. Mechanical, well-precedented, covered by a new test. Rollback = revert one commit.

---

### Phase 1 — Delete the silent no-op (~0.5 day) — **DONE (`74449bc`)**

**Problem:** II.3. Three stacked defects, all reporting health while doing nothing.

**Paradigm:** deletion. There is no proposer to wire this to; building one is a feature, and the
paper's Group B says it is a feature with no evidence behind it. Removing beats stubbing because a
stub is what caused the problem.

| Step | Change |
|---|---|
| 1.1 | Delete `SkillOptFlow._run_self_improvement` and its call site (`skill_opt_flow.py:421-427`) |
| 1.2 | Delete the `self_improver` and `self_improve_contracts` fields from `SkillOptFlowConfig` (Phase 0) and the now-unused `SelfImprover` import |
| 1.3 | Delete `application/services/meta_self_improver.py` (zero call sites) |
| 1.4 | Remove `meta_self_improver.py` from `_META_ALLOWED_TARGET_DIRS` in `self_improver.py` — a self-edit allowlist pointing at a deleted file is itself a lie |
| 1.5 | Decide `MetaImprovementLog` and `METACOGNITIVE_IMPROVEMENT_ENABLED`: the log is referenced by four `tasks/specs` documents as the intended audit substrate for future work. **Keep both**, and add a module docstring line recording that its only consumer was removed |
| 1.6 | Drop the two `meta_self_improver.py` entries from `tests/unit/test_architecture_fitness.py` (lines 128, 768) |

**Keep:** `SelfImprover` itself. `propose_patch` / `validate_patch` / `apply_patch` / `revert_patch`
are all functional and correct; the service has no proposer *in this call path*, which is a wiring
fact, not a defect in the service.

**Acceptance:** `pytest tests/unit/test_architecture_fitness.py -v` green; no import of a deleted
symbol anywhere; `git grep -n meta_self_improver -- '*.py'` empty.

**Risk:** low. Deleting provably unreachable code. Recoverable from git.

---

### Phase 2 — Tabu memory over rejected edits (~2 days) ← highest value-per-line

**Problem:** II.4. **This is the paper's actual 5× mechanism, minus the machinery.**

**Paradigm:** *Value Object* + *Specification* in the domain (pure, total, trivially testable);
*Repository* port with a SQLite adapter for persistence; *Decorator* over `OptimizerPort` so the
flow body is untouched.

#### 2.1 Domain — `domain/models/edit_signature.py`

Frozen Pydantic model. Canonical identity of a proposal:

```
EditSignature = (op, target_normalized, content_fingerprint, direction)
```

- `target_normalized` — case-folded, whitespace-collapsed anchor.
- `content_fingerprint` — a stable hash of normalized content. Deliberately **not** the raw content:
  the tabu list must survive trivial rewordings, or the LLM escapes it by changing punctuation.
- `direction` — carries §III's constraint from the paper's `TOTAL_BATCH_SIZE` failure. An edit that
  *increases* emphasis on a section is not the same proposal as one that *decreases* it. A tabu
  entry must never block a direction that was never tried.

Constructed by a pure `SkillEdit → EditSignature` function. No I/O.

#### 2.2 Domain — `domain/services/tabu_specification.py`

Pure predicate, mirroring the existing `trajectory_comparator.py` precedent (pure functions over
plain types, `assert`-based `__main__` self-check):

```
is_tabu(candidate: EditSignature, blocked: Sequence[TabuEntry], now_epoch: int) -> bool
```

with **tenure** (entries expire after N epochs — from the paper's `TabuSearchManager`, which
recomputes its list against `iteration <= e["expires_at"]` on every check) and an
**aspiration criterion** (a tabu edit is admitted anyway if its accompanying support count exceeds
the threshold that got it rejected). Tenure is what prevents the Group B failure of permanent
lock-out.

#### 2.3 Application port — `application/ports/edit_memory_port.py`

```
record_rejection(skill_name, version, signature, reason, epoch) -> None
active_tabu(skill_name, now_epoch) -> list[TabuEntry]
record_acceptance(skill_name, signature, score_delta, epoch) -> None
```

#### 2.4 Infrastructure — `infrastructure/persistence/sqlite_edit_memory.py`

Adapter on the existing SQLite/WAL substrate, following `sqlite_state_repo` conventions. One table,
indexed on `(skill_name, expires_at)`.

#### 2.5 Application — `application/services/tabu_optimizer.py`

**Decorator** implementing `OptimizerPort`, wrapping the real `OptimizerAgent`:

- on `reflect_on_failures` / `reflect_on_successes`: fetch active tabu, append a rendered
  **"Already tried and rejected — do not re-propose"** block to `evolution_context` (the existing
  injection channel, `optimizer_agent.py:283`), then **filter** returned edits whose signature is
  tabu and not aspirated. Prompt-level discouragement plus code-level enforcement — the paper's
  mechanisms enforce in code, and an LLM instruction alone is not a mechanism.
- on `rank_edits`: pass through.

Registered in DI by wrapping the existing `optimizer_port` binding. `SkillOptFlow` needs no change —
that is the point of choosing Decorator.

#### 2.6 Close the recording loop

`skill_opt_flow.py:285` currently emits `SkillEditRejected(edit=None)`. Populate `edit`, and call
`record_rejection` for each rejected edit. Symmetrically call `record_acceptance` on the accept
branch so the aspiration criterion has data.

#### 2.7 Tests

- Unit, pure: signature normalization (reworded content → same fingerprint; opposite direction →
  different signature); `is_tabu` truth table; tenure expiry; aspiration override.
- Integration: reject an edit, run the next step, assert the same edit is not re-proposed and that a
  *differently-directed* edit on the same target still is.
- Regression: with an empty tabu store, behaviour is byte-identical to today.

**Acceptance:** in a seeded replay where the optimizer previously re-proposed a rejected edit, it no
longer does; accept-rate over a fixed epoch budget is recorded before and after.

**Risk:** medium — this changes what the optimizer sees. Mitigated by: the decorator is opt-in via
DI, an empty store is a no-op, tenure bounds every block, and the aspiration criterion prevents
permanent exclusion. Rollback = unregister the decorator.

---

### Phase 3 — Mechanism selection without code generation (~3 days)

**Problem:** weebot's proposal mechanism is fixed at design time. The paper's evidence says the
*structure* of the mechanism is the high-leverage surface — and that the choice of which structure
should follow from the observed failure mode, not from an author's guess.

**Refused:** LLM writes and injects Python (§III).

**Paradigm:** *Strategy* + *Registry* + a **Policy** selector. The LLM performs Level 2's Explore and
Critique rounds — diagnose the trace, choose a mechanism, set its parameters — and the Specify and
Generate rounds are replaced by selection from a curated, pre-reviewed, individually-tested set. The
paper's own data supports this substitution: code generation was never the bottleneck (§I.3c); five
of six mechanisms were drawn from four named domains the prompt had already suggested.

| Step | Change | Layer |
|---|---|---|
| 3.1 | `ProposalMechanismPort` — a Strategy interface with `pre_reflect(context) -> str` and `post_reflect(edits) -> list[SkillEdit]` hooks | `application/ports/` |
| 3.2 | Concrete strategies, each a small pure-ish class: `TabuMechanism` (Phase 2, refactored to implement the port), `OrthogonalExplorationMechanism` (forbid consecutive proposals against the same section — the paper's DOE mechanism), `BanditMechanism` (adapt the existing `ThompsonSampler` to the port — weebot already owns this one) | `application/services/mechanisms/` |
| 3.3 | `MechanismRegistry` — name → factory, plus declared parameter schema per mechanism | `application/services/mechanisms/` |
| 3.4 | `MechanismSelector` — LLM call over the epoch trace returning **Pydantic-validated** `{mechanism_name, params, rationale}`; unknown name or schema violation ⇒ keep the incumbent and log at WARNING. Runs at epoch boundary only | `application/services/` |
| 3.5 | Composition: strategies compose as a chain, so Tabu + Orthogonal can be active together | `application/services/mechanisms/` |
| 3.6 | Selection decisions are appended to `MetaImprovementLog` (kept in Phase 1.5) — the audit substrate now has a real consumer | `infrastructure/persistence/` |

**Explicitly not implemented:** any path where model output becomes executable code. The selector
chooses among reviewed implementations and sets declared parameters. Nothing else.

**Acceptance:** an A/B over a fixed task set — fixed mechanism vs. selector-driven — reporting
accept-rate and best-score delta. Selector failures degrade to the incumbent with a log line, never
silently.

**Risk:** medium. Contained by the Pydantic-validated selection boundary and by every strategy being
independently unit-tested before it can be selected.

---

### Phase 4 — Instrument Level 1.5 before extending it (~1 day, runs in parallel with 2–3)

**Problem:** Group B says weebot's existing L1.5 machinery may be contributing nothing. Nobody can
currently tell, because nothing measures it.

**Paradigm:** *Observer* on the existing event bus — no changes to the measured code, which is the
only way to trust the measurement.

| Step | Change |
|---|---|
| 4.1 | Subscriber over `SkillEditAccepted` / `SkillEditRejected` / `EpochCompleted` computing per-epoch accept rate, mean score delta, and repeat-proposal rate |
| 4.2 | Flags to disable `slow_update`, `meta_skill`, and `evolution_context` independently — weebot's own Group A/B |
| 4.3 | A short report comparing all-on vs. each-off over a fixed task set |

**Acceptance:** a numeric answer to "does `evolution_context` change the accept rate at all?" —
whatever the answer is. **Repeat-proposal rate is also the pre-fix baseline that makes Phase 2's
effect measurable**, so 4.1 should land before Phase 2 completes.

---

### Phase 5 — Deferred / declined

| Item | Disposition |
|---|---|
| Level 2 runtime Python injection | **Declined.** §III. Revisit only with n ≥ 10 and a sandboxed executor. |
| Recursive bootstrapping (L2 improves L2) | **Deferred.** Not demonstrated in the paper. Needs Phase 3 in production with real accept-rate data first. |
| Misalignment journal → Evolution Agent | **Deferred**, not cancelled. L1.5-shaped; re-rank after Phase 4 reports. |
| Live experience → skill loop | **Deferred**, same reasoning. |

---

## Part V — Sequencing, risk, verification

```
Phase 0 ──┬── Phase 1 ──┬── Phase 2 ──── Phase 3
          │             │
          └── Phase 4 ──┘        (4.1 lands before 2 completes)
```

Phase 0 is a hard gate: phases 1–4 all touch code that cannot currently execute.

| Phase | Effort | Risk | Rollback |
|---|---|---|---|
| 0 | 1d | low | revert commit |
| 1 | 0.5d | low | revert commit |
| 2 | 2d | medium | unregister decorator; empty store is a no-op |
| 3 | 3d | medium | selector off ⇒ fixed mechanism |
| 4 | 1d | low | observer only, no production path |

**Standing verification rules for this work:**

1. No phase is complete until its acceptance criterion has been *run*, not reasoned about.
2. Every new component fails loudly. Given that this plan exists because of two silent no-ops and
   one dead constructor, any new fallback path logs at WARNING with the reason. No component may
   return a success-shaped result without doing its work.
3. Every fitness-test exemption added must name the reason inline.
4. Phase 2 and 3 both change what the optimizer proposes — each needs a before/after number on the
   same task set, not a narrative.

---

## Part VI — Summary

The paper's transferable content for weebot is not its technique. It is:

- a **negative result** that de-ranks two of weebot's standing self-improvement recommendations from
  "expected win" to "measure first";
- a **specific diagnosis** — LLM proposal repetition, up to 22 wasted iterations in 30 — that weebot
  is fully exposed to and has no defence against;
- a **carrier-independence argument** that licenses taking the structural benefit through a Strategy
  registry instead of runtime code injection;
- a **named failure mode**, silent fallback, that weebot exhibits in two places found while
  verifying this analysis.

The largest finding is not from the paper at all. weebot's entire skill-optimization subsystem —
the loop all of this would improve — raises `TypeError` on construction and has never run. Phase 0
is worth more than everything after it.
