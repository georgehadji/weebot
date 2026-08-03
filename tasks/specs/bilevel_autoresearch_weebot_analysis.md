# Bilevel Autoresearch vs weebot — Analysis

**Paper:** Qu & Lu, *Bilevel Autoresearch: Meta-Autoresearching Itself*, arXiv:2603.23420v2 (2 Jun 2026)
**Repo:** https://github.com/EdwardOptimization/Bilevel-Autoresearch
**Analysed:** 2026-08-03 · weebot @ `c6046fc`

---

## 1. What the paper says

Three nested levels over an LLM-driven optimization loop:

| Level | Target | Example |
|---|---|---|
| **1** — inner loop | the task | propose hyperparam change → train → eval → keep/discard |
| **1.5** — outer config | *parameters of* the existing mechanism | freeze stalled params, inject guidance string |
| **2** — mechanism research | *structure of* the mechanism | write new Python search operator, inject at runtime |

Level 2 runs a 4-call dialogue (Explore → Critique → Specify → Generate), patches `runner.py`,
validates by `importlib` import, reverts on failure.

**Headline result** (GPT pretraining benchmark, Δ val_bpb, n=3):

| Group | Levels | Mean Δ |
|---|---|---|
| A | 1 | −0.009 ± 0.002 |
| B | 1 + 1.5 | −0.006 ± 0.006 |
| C | 1 + 1.5 + 2 | **−0.045 ± 0.030** |
| D | 1 + 2 | −0.034 ± 0.031 |

Two claims matter for us:

1. **Level 1.5 bought nothing.** Group B is *numerically worse* than plain Group A. Parameter-level
   tuning of a fixed mechanism increased search diversity but not outcome.
2. **Level 2 was ~5×.** Structural mechanism change did the work. The generated mechanisms
   (Tabu Search, Multi-Scale Bandit, Orthogonal Exploration) all did the same thing: **break the
   LLM's deterministic proposal repetition.** Group A re-proposed the same two edits for 30
   iterations, accumulating 22 consecutive discards.

The decisive discovery in the winning runs was reducing `TOTAL_BATCH_SIZE`. Groups A/B never found
it — the LLM's prior says "bigger batch is better", so it tried an *increase* first, failed, and
Level 1.5 then *froze the parameter*, permanently blocking the decrease direction. **The outer
config loop actively caused the miss.**

Sample size is n=3 with σ ≈ 67% of the mean, one benchmark, one model. Treat the 5× as directional.

---

## 2. What weebot already has

Verified by reading source, not grep.

| Paper level | weebot equivalent | Status |
|---|---|---|
| Level 1 | `SkillOptFlow` — rollout → reflect → merge → rank → apply → validate → accept/reject → slow update ([skill_opt_flow.py](../../weebot/application/flows/skill_opt_flow.py)) | **Written richer than the paper's** (evaluator co-evolution, adversarial pool, selective erasure, Thompson archive search) — but **unreachable**, see §3.0. |
| Level 1.5 | `slow_update` + `meta_skill` at epoch boundary; `EvolutionTracker` longitudinal narrative; `SelfImprover` patching contract YAML / rule MD | **Present.** |
| Level 2 | — | **Absent.** No component generates or replaces the *structure* of the search loop. |

weebot's `thompson_sampler` archive search is a bandit — i.e. weebot already ships, hand-written,
one of the three mechanisms Level 2 discovered on its own. That is the paper's exact point about
prior systems: good mechanisms, chosen by humans.

`MetaSelfImprover` ([meta_self_improver.py](../../weebot/application/services/meta_self_improver.py))
*looks* like Level 2 but is not — it reviews whether a **strategy string** should be rewritten.
That is Level 1.5. It is also never constructed anywhere in the repo.

---

## 3.0 Blocking bug — the SkillOpt subsystem cannot be constructed

[`_skillopt.py:83`](../../weebot/application/di/_skillopt.py:83) calls `SkillOptFlow(...)` with
kwargs that do not match [`skill_opt_flow.py:46`](../../weebot/application/flows/skill_opt_flow.py:46):

```
UNEXPECTED kwargs passed by DI : ['optimizer_llm', 'scorer', 'target_factory']
REQUIRED params DI never passes: ['event_bus', 'optimizer', 'target_flow_factory']
```

Runtime: `TypeError: SkillOptFlow.__init__() got an unexpected keyword argument 'optimizer_llm'`.
Python raises before the constructor body runs — no input succeeds. Both entry points are dead
([`run.py:277`](../../run.py:277), [`cli/commands/flow.py:216`](../../cli/commands/flow.py:216)).

So every L1 capability listed above is unexecuted code. Nothing measured about weebot's optimization
loop means anything until this is fixed. See Phase 0 of the implementation plan.

## 3. Bug found while verifying — `_run_self_improvement` is a guaranteed no-op

Three defects stacked, in [skill_opt_flow.py](../../weebot/application/flows/skill_opt_flow.py):

**(a) The call can never produce a patch.** `_run_self_improvement` builds its context with:

```python
context = {
    "target_file": rel_path,
    "target_type": "contract",
    "current_content": current,
    "new_content": current,  # No change unless optimizer proposes one
    ...
}
patch = await self._self_improver.propose_patch(context)
```

`SelfImprover.propose_patch` then does:

```python
if current_content == new_content:
    logger.info("No change detected — skipping patch")
    return None
```

`new_content` is *literally* `current`. Every iteration, for every contract YAML and every rule MD,
returns `None`. Nothing is ever patched. The comment "unless optimizer proposes one" describes a
call that does not exist — **`SelfImprover` has no proposer.** `propose_patch` only *diffs* two
strings it is handed; nothing in the codebase generates the second string.

**(b) The branch is unreachable anyway.** `self_improve_contracts: bool = False` and no caller ever
passes `True` — the only three references to it are inside `skill_opt_flow.py` itself.

**(c) `MetaSelfImprover` is dead.** Zero constructor call sites repo-wide.

Same class as `delegate_task` (deleted this session) and `subagent_rpc`'s stub-success: **code that
reports health while doing nothing.** Here it even logs at INFO level, so a run looks fine.

Note the paper hit the identical failure mode and calls it out as a limitation — its Level 2 dynamic
loader had a `sys.modules` registration bug causing *silent fallback to the original runner*,
invalidating an entire experimental run before they caught it. Their words: silent fallback without
error is a dangerous failure mode.

---

## 4. Verdict — what to actually take

### Take: the prioritization signal (free, changes what we build next)

Two prior audits recommended closing loops that are all Level 1.5 or below:

- Code-as-Harness: feed the misalignment journal into the Evolution Agent
- Memento: close the live experience → skill loop

The paper's Group B is direct evidence that this class of work — richer context into a fixed
proposal/accept mechanism — is where gains fail to materialize. Worse, its Level 1.5 *caused* the
miss by freezing a parameter after one failed direction. weebot's `slow_update`, `meta_skill`, and
`evolution_context` are all the same shape: more text into an unchanged loop.

Not a reason to cancel that work. It is a reason to stop expecting it to be the win, and to
instrument it (does accepted-edit rate actually move?) rather than assume.

### Take: the failure diagnosis, which weebot can act on cheaply

The mechanism that produced the 5× was not sophisticated. It was **"stop re-proposing what you
already tried."** Group A burned 22 of 30 iterations on repeats.

weebot's optimizer proposes edits from `evolution_context` = last 5 epoch narratives
(`_build_evolution_context`). It has **no record of rejected edits** — `SkillEditRejected` is
yielded as an event and dropped. The optimizer can, and by the paper's evidence will, re-propose
the same rejected edit indefinitely.

A tabu list of rejected edit signatures fed into the reflect prompt is ~30 lines against existing
structure, needs no code generation, no runtime injection, no new subsystem. That is the paper's
result, minus the machinery.

### Don't take: runtime Python code injection

Level 2's carrier is `exec`-adjacent self-patching of the live runner. Against weebot that means
handing an LLM write access to `application/flows/`. weebot's `SelfImprover` allowlist deliberately
refuses `.py` outside a flag-gated two-file meta tier — that restraint is correct and should stay.
The paper's own limitations section lists no stability guarantee, unconstrained third-party imports,
and the silent-fallback bug. n=3 on one benchmark does not buy that risk.

The paper itself says code is only one carrier and the framework is representation-agnostic. weebot
already has safer carriers — skills, prompts, contracts, evaluators — with validation and rollback.

---

## 5. Recommended actions

| # | Action | Size | Why |
|---|---|---|---|
| 1 | Fix or delete `_run_self_improvement` + `self_improve_contracts` + `MetaSelfImprover` | small | Silent no-op advertising a capability that does not exist. Deletion is the honest option — there is no proposer to wire it to. |
| 2 | Persist rejected edits; feed signatures into the reflect prompt as a tabu list | ~30 LOC | The paper's actual 5× mechanism. Highest value-per-line here. |
| 3 | Instrument Level-1.5 machinery (`slow_update`, `meta_skill`, `evolution_context`) with accept-rate deltas | small | Group B says assume nothing. Measure before extending. |
| 4 | Level 2 code injection | — | **Declined.** Risk >> n=3 evidence. |

Action 1 is a bug fix in scope of the active session goals. Actions 2–4 are proposals, not started.
