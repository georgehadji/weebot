# LongHorizon-Harness → weebot: analysis and enhancement plan

**Date:** 2026-08-09
**Sources:** arXiv 2608.01964 (Ma et al., DreamX Team / Alibaba); `github.com/AMAP-ML/LongHorizon-Harness` (`src/lh_harness/`, 30 modules, read at `main`)
**Method:** paper read in full (29 pp); harness source downloaded and read; every weebot claim below verified by reading the file, not grep alone.
**Actionable plan extracted to:** [`longhorizon_harness_implementation_plan.md`](longhorizon_harness_implementation_plan.md)

---

## 1. What the paper actually claims

The headline numbers are not the contribution. The contribution is a **reframing**: long-horizon execution is a *task-state management* problem, not a context-length problem.

Two structural limitations it names in existing harnesses (Claude Code, Codex CLI, OpenClaw — and, as shown in §3, weebot):

1. **Execution and state-management share one growing context.** The agent uses the same context to do the work and to remember what it has done.
2. **Execution and completion assessment are coupled.** The agent performs a subtask *and judges whether it succeeded*. A wrong judgment gets recorded as state and becomes a premise for later decisions.

The fix is the **Manage–Execute–Audit (MEA) loop**:

| Role | Sees | Can do | Cannot do |
|---|---|---|---|
| **Manager** | task `T`, state `Sᵢ`, all audit reports `Vᵢ` | maintain state, emit one bounded subtask contract | **touch the environment at all** |
| **Executor** | `T`, `Sᵢ`, contract `cᵢ`, only the audit reports the contract references | modify the environment | see prior raw trajectories |
| **Auditor** | `T`, `Sᵢ`, `cᵢ`, executor report `oᵢ` | read-only environment inspection | see executor's raw trajectory/reasoning; mutate anything |

The load-bearing invariants:

- **`oᵢ` (executor report) never advances state.** Only `vᵢ` (audit report) does. "A record is marked as completed only when supported by clean audit evidence."
- **Task state is typed and provenance-linked.** Records are `requirement` | `artifact` | `fact`, each marked `completed | pending | blocked | **untrusted**`, each retaining references to the audit evidence supporting its status.
- **Audit reports are the *only* cross-round memory.** Executor trajectories are discarded each round.
- **Audit is three-axis, not pass/fail:** completion (`complete|incomplete|blocked`), integrity (`clean|suspect|violation`), contract alignment (`aligned|unknown|needs_revision|invalid`).

### Results, with the caveats the paper itself supplies

| Benchmark | Baseline | LH-Harness | Δ |
|---|---|---|---|
| WeaveBench PassRate (Qwen 3.7-Plus) | 51.8 | 80.7 | +28.9 |
| Terminal-Bench 2.1 (Qwen 3.7-Plus) | 69.7 | 77.2 | +7.5 |
| OSWorld 2.0 binary (Qwen 3.7-Plus) | 2.8 | 8.3 | 3.0× |
| OSWorld 2.0 subset (Claude Opus 4.7) | 20.6 | 35.3 | +14.7 |

**The mechanism is failure-floor recovery, not ceiling-raising.** On the 17 WeaveBench Games tasks, all six where the Qwen baseline scored ≤0.04 recovered to 0.30–0.92. Tasks the baseline already solved sometimes *regressed* (rhythm_autoplay 0.95→0.83, pysol 0.52→0.41). Same pattern at the domain level: Desktop mean score went **down** (−0.0205) while its pass rate went up (+5.56 pp).

**Where it does not help — stated plainly by the authors.** Terminal-Bench regressions: data-science −0.125, mathematics −0.167, video-processing −0.333, mteb −0.333. Their explanation: "Independent auditing can detect an incorrect result and initiate recovery, but it cannot supply a capability that the model does not possess." Gains scale with *long-horizon execution reliability* being the bottleneck, not with GUI vs CLI. By difficulty: hard +0.122, medium +0.042.

**Cost is not a fixed multiplier.** Manager is 2.0–8.1% of tokens; auditor is 19.4–38.1%. Total: 2.3× on WeaveBench, 3.6× output tokens on OSWorld — but **−24% on Terminal-Bench**, with a higher success rate. And per-model it inverts: Qwen 10.7M→34.3M, Opus 16.5M→**11.1M**. A capable executor satisfies contracts in fewer audit–replan rounds, so auditing pays for itself by preventing flailing.

---

## 2. What the repo implements that the paper does not describe

The paper is the *why*; the source is where the enforceable engineering lives. The parts worth stealing:

**Fail-closed audit parsing.** The auditor must emit exactly three control lines. A missing/malformed header produces `_invalid_control_header_report` — the harness refuses to infer completion from prose (`auditor_agent.py:73`, `:433`, `:441`). And a `complete` verdict is **downgraded** whenever integrity is `violation` or contract audit isn't `aligned` (`auditor_agent.py:279`, `:304`).

**Read-only enforced mechanically, not by instruction.** The harness snapshots the workspace before the audit episode and diffs after. Any mutation sets `verifier_workspace_mutation_detected`, forces `integrity: violation`, restores the snapshot, and invalidates the audit (`prompt_texts.py` keys `read_only_violation`, `runtime_mutation_restored`/`_not_restored`; reconciliation in `auditor_agent.py:711–780`). Telling a model "don't mutate" is not the control; the diff is.

**Artifact provenance as a first-class check.** `save_screenshot` writes a `.meta.json` with `capture_source=real_screen`; the auditor is instructed to inspect it (`prompt_texts.py:185`). The CAD case study audits five screenshots for distinct md5s and strictly increasing mtimes. The lesson generalizes past GUI: *artifact presence is weaker than artifact validity.*

**Acceptance constraints must be derived from the request and real environment facts** — "a plan, model guess, or easier substitute is not an acceptance constraint" (`prompt_texts.py:14`), with an explicit `Acceptance-constraint backcheck:` section required in every audit.

**Round-one epistemics.** "hypotheses may come from the request, but current desktop, file, webpage, application, or service facts must remain unverified until confirmed by an auditor or direct environment evidence" (`prompt_texts.py:11`). Every manager fact must cite an audit round (`round_003`) or be labelled unverified (`:82`).

Also worth noting: per-role budgets (`manager/auditor 600s`, executors `1800s`), `AgentAdapter` keeping each backend's native ReAct loop intact, and a `types.py` that is a plain dataclass file — the whole state contract is ~190 lines.

---

## 3. Gap analysis against weebot — verified against code

weebot has more machinery than LH-Harness in most dimensions (CQRS, cascading, circuit breakers, skills, KG, misalignment journal). The gap is narrow and specific: **weebot has no independent completion authority.** Every finding below was confirmed by reading the file.

### 3.1 The executor declares its own steps complete — CONFIRMED

[`executor/_base.py:951`](weebot/application/agents/executor/_base.py:951) yields `StepStatus.COMPLETED` whenever the step loop finished without a `loop_error`. The failure condition (`:928–941`) only trips if `tool_calls_attempted > 0 AND tool_calls_succeeded == 0 AND no output`. An executor that emits plausible text and touches nothing real still reports COMPLETED. [`executing.py:512`](weebot/application/flows/states/executing.py:512) then commits it to the plan.

This is exactly the paper's structural limitation (ii).

### 3.2 Verification is terminal and reads the executor's own claims — CONFIRMED

[`VerifyingState`](weebot/application/flows/states/verifying.py) runs **once, after every step is already marked COMPLETED** ([`executing.py:137`](weebot/application/flows/states/executing.py:137)). Worse, its "independent" answering step builds its evidence block from `ToolEvent.result` — the executor's own outputs ([`verifying.py:583–600`](weebot/application/flows/states/verifying.py:583)). The docstring is candid that this deviates from CoVe, and the reasoning given (a verifier with zero context answers "I don't know") is sound — but the resolution imports the executor's narrative instead of inspecting the environment. That is precisely what the paper's auditor is defined *against*.

### 3.3 Verification gates fail open — CONFIRMED

- [`_check_consistency` returns `True` on any exception](weebot/application/flows/states/verifying.py:639) — "Assume consistent on failure — don't block completion."
- [`_score_output` returns passing scores on any exception](weebot/application/flows/states/verifying.py:232).

The second already logs a warning admitting the gate "silently not running is exactly what an operator needs to see" — but the run still completes with a clean stamp, and a not-run gate is indistinguishable downstream from a passed one. LH-Harness fails **closed** in the same situations.

### 3.4 No task-state record — CONFIRMED

[`Step`](weebot/domain/models/plan.py:25) is `{id, description, status, result, retry_count}`. `StepStatus` has no `untrusted`. There are no acceptance criteria, no boundary constraints, no evidence references. Facts go into the session via `set_fact` straight from executor extraction ([`executing.py:527`](weebot/application/flows/states/executing.py:527)) with no provenance and no trust level — an unverified executor claim becomes a durable premise, which is the paper's failure mode (i).

### 3.5 weebot's `AuditService` exists but is not in the loop — CONFIRMED

[`AuditService`](weebot/application/services/audit_service.py) is registered in DI (`di/_factories.py:95`) and exposed as [`AuditTool`](weebot/tools/audit_tool.py) via `tool_discovery.py:62`. **No flow or state calls it.** It is reachable only if the LLM happens to invoke the tool. It is also regex-matching over an output *string*, not environment inspection. Consistent with the standing weebot pattern: the constraint is unwired capability, not missing capability.

`weebot/application/harness/` is a **benchmark** harness (`BenchmarkRunner`/`TaskLoader`/`TaskScorer`), unrelated to MEA — the name collision is worth keeping in mind when naming new modules.

### 3.6 Cross-step context is compacted narrative, not audited fact — CONFIRMED

`self._conversation_buffer` persists across steps with periodic compaction ([`_base.py:565`](weebot/application/agents/executor/_base.py:565)). Compaction summarizes the executor's own narrative, so unverified claims survive the boundary in compressed form. The paper's rule is that only audited facts cross the round boundary.

### 3.7 The routing decision that would gate verification depth is computed and discarded — CONFIRMED

Relevant because the paper's regressions make *selective* application mandatory, and the mechanism for it is already built:

- [`factories.py:89`](weebot/interfaces/factories.py:89) — `route_and_create_flow` computes `TaskRoute(category, complexity)` on every query. Live, on the real path.
- [`factories.py:142–143`](weebot/interfaces/factories.py:142) — `create_flow` reads **only** `task_route.flow_type`. Category and complexity are dropped.
- [`task_preset.py`](weebot/domain/models/task_preset.py) defines `TaskPreset` with exactly the right knobs, and [`task_preset_registry.py`](weebot/config/task_preset_registry.py) registers three tiers.
- Three flow states already read it: [`premortem.py:37`](weebot/application/flows/states/premortem.py:37), [`executing.py:461`](weebot/application/flows/states/executing.py:461), [`critiquing.py:87`](weebot/application/flows/states/critiquing.py:87).
- But `get_preset()` has **zero production callers** — only `tests/unit/test_task_preset.py`. `PlanActFlow.__init__` ([`plan_act_flow.py:95–107`](weebot/application/flows/plan_act_flow.py:95)) does not accept `task_preset`, and `create_flow` uses that kwarg path. So `cfg.task_preset` is always `None`, `_task_preset` is always `None`, and every preset gate falls through to its default.

Same shape as §3.5: the capability is built and unwired. Selective verification depth is a wiring change, not a subsystem.

### 3.8 Where weebot is already ahead

Worth stating so the plan doesn't regress anything: `ConstraintExtractor` + pause-for-user on violation ([`executing.py:186–219`](weebot/application/flows/states/executing.py:186)) has no LH-Harness equivalent; the artifact gates in `_gate_artifact_verification` ([`verifying.py:432`](weebot/application/flows/states/verifying.py:432)) *do* hit the real filesystem (`Path(p).exists()`), check test-output failure markers, and detect SVG-disguised placeholder images. **That last one is genuine environment-grounded auditing — it is simply running at the wrong time (once, at the end) and checking existence rather than acceptance.**

---

## 4. Enhancement plan, ranked

Ranking is (evidence strength × verified weebot gap) ÷ implementation cost. E1–E3 are the ones that matter; the rest are supporting.

### E1 — Hoist artifact gates to per-step, and make them the completion authority ★ highest value
**Change:** before [`executing.py:512`](weebot/application/flows/states/executing.py:512) marks a step COMPLETED, run the environment-grounded checks that currently live in `_gate_artifact_verification` — scoped to *this step's* events. If they fail, the step does not become COMPLETED.
**Why this first:** it reuses code that already exists and already reads the environment; it needs no new agent, no new model calls, no token cost. It converts weebot's single strongest existing verification asset from a terminal report into a gate. It directly closes §3.1 and §3.2.
**Watch:** `_all_tripped` at [`executing.py:415`](weebot/application/flows/states/executing.py:415) force-marks COMPLETED when all models are circuit-broken. That path must set the new `UNVERIFIED` status instead, or it becomes a silent bypass.

### E2 — Add `UNVERIFIED` to `StepStatus`, and acceptance criteria + evidence refs to `Step`
**Change:** `StepStatus.UNVERIFIED`; `Step.acceptance_criteria: list[str]`; `Step.evidence_refs: list[str]`. `PlannerAgent` emits criteria per step (this is the paper's subtask contract `cᵢ`). `is_done()` must treat UNVERIFIED as not-done so the plan-update loop can route it.
**Why:** without a per-step acceptance criterion there is nothing for E1 to check *against* — "the file exists" is presence, and the paper's clearest empirical lesson is that presence ≠ validity. This is what makes E1 more than an existence check.
**Cost:** touches `plan.py`, `planner.py`, and every `is_done()` caller. Grep all callers before changing — the standing lesson from `verify-scope-lesson`.

### E3 — Give session facts provenance and a trust level
**Change:** `set_fact(key, value, *, source: Literal["executor","audit","user"], verified_by: str|None)`. Facts from `executing.py:527` land as `source="executor"`, unverified. Only environment-confirmed facts get `source="audit"`. Planner/executor prompts render unverified facts as explicitly unverified.
**Why:** closes §3.4. This is the paper's fix for compounding error, and it is cheap — a signature change plus a render change, not a new subsystem.

### E4 — Make the verification gates fail closed
**Change:** [`verifying.py:639`](weebot/application/flows/states/verifying.py:639) and [`:232`](weebot/application/flows/states/verifying.py:232) must not return a passing value on exception. Record a distinct `verification_status: "not_run"` and surface it in the completion stamp.
**Why:** a not-run gate currently reads as a passed gate. The existing warning log proves the author saw it; the behaviour just wasn't changed. Small diff, removes a false-confidence source.
**Note:** this will surface real failures that are currently swallowed. Expect noise on first run — that's the point, but stage it after E1 so there is a real gate behind it.

### E5 — Gate verification *depth*, not verification itself

**Why any gating is required:** the paper's own data. Hard +0.122 vs medium +0.042 (Table 10); regressions concentrated in data-science, mathematics, mteb, video-processing (Tables 9, 11); auditing is 19–38% of tokens. Applying MEA universally would make weebot *worse* on short analytical tasks while costing more.

**The discriminant is not task complexity.** Look at where the paper actually regresses: mathematics, data-science analysis, mteb, video. What those share is not difficulty — it is that they produce **no durable external state**. The gains are on files, terminal, and GUI: tasks that mutate an environment. So the predicate is not *how hard is this task* but **does this step leave evidence outside the model's own text**.

That predicate is better than a classifier on three counts: it is per-step rather than per-task, it is derivable from the step's own `ToolEvent`s with zero model calls, and it self-selects — a step that wrote a file gets checked against the file, a step that only reasoned has nothing to check, and auditing it is precisely the token spend the paper measures as harmful.

Do not lean on the complexity estimate for this. [`_estimate_complexity`](weebot/application/services/keyword_task_router.py:121) is keyword matching: `"create a summary of this data"` hits `"create"` and returns `HIGH` — exactly backwards for the category that regresses.

**Depth ladder:**

| Tier | Trigger | Cost | What runs |
|---|---|---|---|
| 0 | step has environment-touching `ToolEvent`s | **0 tokens** | the mechanical checks — `Path(p).exists()`, test-failure markers, placeholder-image detection. This *is* E1. |
| 1 | Tier 0 found evidence but cannot judge acceptance | 1 cheap-model call | evidence vs. `Step.acceptance_criteria` (E2) |
| 2 | preset is `complex` **and** Tier 1 returns `needs_revision` | full audit + replan | the paper's actual MEA round |

Tier 0 costs nothing, so it should be universal — that is the whole point of E1 reusing existing code. The paper's 19–38% overhead is entirely Tiers 1–2, and **those** are what the preset gates. Stated once: *the evidence check is universal because it is free; the model-based audit is gated.*

Tier 0's input already exists — `_current_step_events` at [`executing.py:472`](weebot/application/flows/states/executing.py:472) is exactly the per-step scoping it needs.

**Change (the wiring from §3.7):**

```python
# factories.py — carry the route through instead of discarding it
preset = get_preset(
    "simple"  if task_route.complexity is TaskComplexity.LOW else
    "complex" if task_route.category is TaskCategory.COMPLEX else
    "standard"
)
```

Then thread `task_preset=preset` through `PlanActFlow.__init__` into `PlanActFlowConfig`. Add one field to `TaskPreset`:

```python
audit_depth: int = 1   # 0 = evidence only, 1 = +acceptance check, 2 = +replan
```

`simple` → 0, `standard` → 1, `complex` → 2.

**Watch:** setting `_task_preset` to a non-`None` value for the first time also activates the two gates that have never fired in production — `enable_premortem` on complex, and `enable_step_validation=False` on simple. Real behaviour change on untested paths. Land the wiring and the `audit_depth` field in one commit, and check `PRESET_SIMPLE.enable_step_validation=False` is actually wanted before shipping it.

### E6 — Run manager/verifier roles on a cheaper cascade tier
**Change:** per-role tier constants in `model_cascade_config.py`; verification-role calls enter the cascade at BUDGET, executor stays PREMIUM.
**Why:** the paper measures the manager at 2.0–8.1% of tokens — state maintenance is nearly free. And Terminal-Bench was **−24% tokens** with the harness. weebot's `CascadeExecutor` already supports this; it's configuration, not code.

### E7 — Workspace snapshot guard — **only if E1 grows into a tool-using verifier**
**Change:** snapshot-and-diff around any verification episode that gets real tools; mutation ⇒ integrity violation ⇒ audit cannot support completion.
**Why sequenced last:** weebot's verifier currently has no tools, so it *cannot* mutate — the guard is unnecessary today. The moment E1 evolves from reading events to running inspection commands, it becomes mandatory. Flagging now so it isn't forgotten at that boundary.

### Explicitly not recommended

**Do not port fresh-context-per-round executors.** weebot already has `_step_budget`, `TrajectoryMonitor`, and context compaction guarding the 400-step-flailing failure the paper's Figs. 7 and 10 dramatize. The residual gap (§3.6) is *what* crosses the boundary, not *how much* — and E3 fixes that at a fraction of the risk of restructuring the executor loop.

**Do not adopt the three-process role split.** LH-Harness spawns separate Claude Code/Codex episodes per role because it wraps opaque third-party CLIs. weebot owns its executor; it can enforce the same invariants in-process at far lower cost. The invariant worth copying is *"executor claims never advance state"* — not the process topology.

---

## 5. Suggested sequencing

E2 (data model) → E1 (gate = Tier 0) → E4 (fail closed) → E3 (fact provenance) → E5/E6 (depth gating + cost) → E7 (only at the tool-using-verifier boundary).

Rationale: E1 needs E2's acceptance criteria to check against; E4 is only meaningful once a real gate exists behind it; E6 is tuning that should follow a working gate.

E5 is the exception to "tuning comes last". Its Tier 0 *is* E1, so that part ships with E1 by construction. Its wiring half (§3.7 — carry `TaskRoute` into a `TaskPreset`) is ~15 lines and independent of everything else, so it can land any time; but it only *buys* anything once Tier 1 exists, which needs E2. Nothing is gained by pulling it earlier.

**Validation:** the honest test of E1–E4 is a regression task where the executor *claims* success and the environment contradicts it. weebot's `infrastructure/fixtures/regression/` is the right home. Without such a fixture, all of this is unfalsifiable — which is the exact failure the paper is about.
