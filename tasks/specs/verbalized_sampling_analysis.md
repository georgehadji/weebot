# Verbalized Sampling × weebot — Value Analysis

**Paper:** *Verbalized Sampling: How to Mitigate Mode Collapse and Unlock LLM Diversity* (Zhang, Yu, Chong et al., arXiv:2510.01171v3, Oct 2025)
**Analyzed:** 2026-06-15 against the weebot codebase (branch `master`).
**Question:** Where does this paper add *real* value to weebot — not where it could theoretically be sprinkled in.

---

## 1. The mechanism (what the paper actually proves)

**Root cause.** Post-training alignment (RLHF/DPO) causes *mode collapse* — aligned models collapse to a narrow set of "typical" responses. The paper's novel claim is that this is not merely an algorithmic artifact but a **data-level driver**: *typicality bias* in human preference data. Annotators systematically prefer familiar/fluent/predictable text (mere-exposure effect, processing fluency). They model the reward as `r(x,y) = r_true(x,y) + α·log π_ref(y|x) + ε`, fit it on HelpSteer, and find **α ≈ 0.57–0.65 (p < 1e-14)** — i.e. raters reward typicality *independent of correctness*. Any α > 0 sharpens the optimum (γ = 1 + α/β), so even a perfect reward model + optimizer still collapses.

**The fix — three prompt levels (Table 1):**
| Level | Example | Behaviour |
|-------|---------|-----------|
| Instance-level (Direct) | "Tell a joke about coffee" | Collapses to *the* modal response |
| List-level (Sequence) | "Tell 5 jokes about coffee" | Uniform list of related items |
| **Distribution-level (VS, ours)** | "Generate 5 jokes **with their probabilities**" | Approximates the pretraining distribution → recovers diversity |

**Verbalized Sampling (VS)** = ask the model to emit `k` candidates, each wrapped with a verbalized `<probability>`. Variants: **VS-Standard**, **VS-CoT** (reason first, then emit the distribution — best quality on capable models), **VS-Multi** (multi-turn). Diversity is **tunable** by adding a probability threshold ("sample from the tail, prob < 0.10") *without touching decoding params*.

**Evidence (relevant to weebot):**
- Creative writing: **1.6–2.1× diversity** vs Direct, quality preserved (VS-CoT pushes the Pareto front).
- Open-ended QA with many valid answers: **lower KL** to the true distribution, **higher coverage**, **precision stays ≈ 1.0** (diversity does *not* cost correctness).
- Synthetic data generation: VS-generated data is more diverse → **better downstream task accuracy** (37.5% vs 30.6% direct on math SFT).
- **Orthogonal to temperature** and to top-p/min-p — stacks with them.
- **Emergent trend:** *larger/more capable models benefit more* from VS.
- Safety & factual accuracy are **not** degraded (§G.7, §G.8).

**Critical nuance for engineering:** the verbalized probabilities are a **steering/selection device, not calibrated confidence**. The paper itself, for QA, scores the *frequency of generated answers*, not the verbalized numbers. Treat them as a knob for ranking + tail-sampling, never as ground-truth probability.

---

## 2. Where weebot is exposed to mode collapse *today* (grounded)

Every divergent decision in weebot is currently made with an instance- or list-level prompt — exactly the regimes the paper shows collapse:

| Site | File | Prompt level today | Temp | Collapse risk |
|------|------|--------------------|------|---------------|
| Plan creation | [planner.py:247](weebot/application/agents/planner.py:247) | **Instance-level**, single plan | `0.0` (`TEMPERATURE_DETERMINISTIC`) | **HIGH** |
| Plan update / recovery | [planner.py:270](weebot/application/agents/planner.py:270) | Instance-level **+ hand-rolled** "do NOT attempt the same pattern" | `0.0` | **HIGH** — already manually fighting mode collapse |
| ToT recovery candidates | [tree_of_thoughts_scorer.py:80](weebot/application/services/tree_of_thoughts_scorer.py:80) | **List-level** ("generate 3 *different* approaches") | `0.7` | **MEDIUM** — mitigated, but list < distribution |
| Dreamer ideation | [dreamer.py:74](weebot/application/agents/dreamer.py:74) | List-level + hand-rolled `heat_score` | `0.3` | **MED-HIGH** |
| Optimizer/Evolution edits | [optimizer_agent.py:261](weebot/application/agents/optimizer_agent.py:261) | List-level reflection → edits | `0.3` | **MEDIUM** |
| Mixture-of-Agents | [mixture_of_agents.py:99](weebot/tools/mixture_of_agents.py:99) | *Inter-model* diversity, N calls | `0.7` | N/A — different diversity axis |

**The single most important observation:** weebot's [`TreeOfThoughtsScorer`](weebot/application/services/tree_of_thoughts_scorer.py) already implements the paper's *list-level* prompt to escape "local-minimum revision loops," and its scorer explicitly rewards a **`novelty`** axis ([tree_of_thoughts_scorer.py:32](weebot/application/services/tree_of_thoughts_scorer.py:32)). The team already believes in candidate-diversity-for-recovery and built infra for it. The paper proves the *distribution-level* prompt beats the *list-level* one at the **same compute budget** — so VS is an **evidence-backed upgrade to code that already exists**, not a speculative new feature. This is the cleanest possible landing spot.

Likewise, [`planner.update_plan`](weebot/application/agents/planner.py:276) injects a brittle natural-language negative ("Do NOT attempt the same command or pattern") to force a different approach. That *is* a hand-rolled mode-collapse workaround; VS does the same thing principledly by sampling the tail of the distribution.

---

## 3. Tiered value opportunities (most→least defensible)

### Tier 1 — Strong, evidence-backed, lands on existing seams

**A. Upgrade ToT failure-recovery generation: list-level → VS.**
`TreeOfThoughtsScorer.generate_candidates` ([:69](weebot/application/services/tree_of_thoughts_scorer.py:69)) becomes a VS call: "generate N replacement approaches, each with a probability; sample from the tail (prob < threshold) for genuinely novel escapes." The paper's data says this yields more diverse candidates than the current "3 different approaches" list at identical budget. Bonus: the verbalized probability is the **novelty signal the existing scorer already pays a separate LLM-judge call to estimate** ([:108](weebot/application/services/tree_of_thoughts_scorer.py:108)) — so VS can *fold generation + a novelty prior into one call*, cutting the current `1 + N` calls toward `1` (keep a light feasibility judge; that's the axis VS doesn't give you). **Smallest diff, highest confidence.**

**B. VS plan-candidate generation for `create_plan`.**
Today: one plan, temp 0.0 = textbook collapse. For non-trivial tasks there are several valid decompositions, and the first/typical one is often the stereotyped one. Have the planner verbalize `k` candidate plans with probabilities, then select via the **existing ToT scoring pattern** (feasibility/specificity) — reuse, don't reinvent. This is the paper's "open-ended QA with multiple valid answers" applied to planning, where coverage rises and precision holds. Gate behind a complexity check so trivial tasks stay single-shot (cost control).

**C. Principled diversity in `update_plan`.**
Replace the hand-rolled "do NOT repeat the pattern" instruction with a VS tail-sample of recovery strategies. Same intent, grounded in the distribution instead of a negative imperative the model may ignore under collapse.

### Tier 2 — Real, narrower

**D. Dreamer ideation.** The Dreamer's entire job is divergent ideation from signals — the use case most directly hit by collapse (it will keep surfacing the obvious idea). Move from list + hand-rolled `heat_score` to **VS-CoT** (reason over signals, then emit ideas with verbalized probability); tail-sampling surfaces the novel opportunities the harness would otherwise never see. `heat_score` becomes `urgency × verbalized_novelty × confidence`.

**E. Evolution-Agent edit-pool diversification.** `OptimizerAgent.reflect_on_*` ([:51](weebot/application/agents/optimizer_agent.py:51)) generates the candidate `SkillEdit` pool that `merge_edits`/`rank_edits` then prune. If reflection collapses to the typical fix, harness self-improvement converges to a **local optimum**. VS widens the candidate pool *before* the existing merge/rank selector — more exploration, same governance. Directly strengthens the self-improvement loop flagged in [[code_as_harness_analysis]].

**F. Synthetic held-out eval/regression suite.** The `RegressionGate` infra exists (held-in/held-out, `min_held_out_tasks`, [cli/commands/harness.py:193](cli/commands/harness.py:193)) but a *diverse task suite* must be supplied. §8 is precisely "VS generates more diverse synthetic data that improves downstream metrics." Use VS to synthesize a **diverse** held-out task/failure-scenario suite rather than a handful of hand-written cases — diversity here is exactly what makes a regression gate trustworthy. Fills the "held-out suite deferred to Phase 4" gap from the prior analysis with the paper's proven method.

### Tier 3 — Note, don't oversell

**G. Creative/content interfaces** (website/LinkedIn/portfolio generation; e.g. `examples/linkedin_post.py`, the `Output/*-website` artifacts). Creative writing is the paper's home turf (1.6–2.1×). VS here is the operational enforcement of the user's own **anti-template / anti-AI-slop** web rules — it structurally fights the "default template look." Value scales with how much weebot is used for content vs. ops.

**H. VS as a cheaper first tier vs. Mixture-of-Agents.** MoA buys *inter-model* diversity at N provider calls + an aggregator. VS buys *intra-model* diversity in **one** call. For tasks where single-model diversity suffices, VS is a far cheaper first tier; escalate to MoA only when cross-model disagreement is the point. **Complement, not replacement** — be honest that VS cannot replicate diversity that comes from different training corpora.

---

## 4. Unifying architecture recommendation

VS is *pure prompting + a structured-output schema*, so it fits weebot's Clean Architecture with **no port change**:

- **`VerbalizedSampler` (application service)** wrapping the existing `LLMPort.chat`:
  - Input: base instruction, `k`, optional `probability_threshold`, variant (`standard`/`cot`).
  - Output: `SampledDistribution[T]` — list of `(text/payload, verbalized_probability)`, parsed from the paper's `<response><text/><probability/></response>` schema and validated by a Pydantic model under `weebot/models/structured_output.py` (honors the Structured Output Protocol).
  - Selection strategies: `mode` (argmax prob), `weighted_sample`, `tail` (prob < threshold → exploration/novelty).
- **Route VS calls to the capable model tier** via `ModelCascadeService` — the paper's emergent trend (larger models benefit more) means VS is wasted on the FREE tier.
- **Consumers:** ToT recovery (A), planner candidates (B/C), Dreamer (D), Optimizer (E), synthetic-data CLI (F) all call the one service → DRY.
- **Opt-in, divergent steps only.** Never wrap convergent execution or structured tool-argument generation in VS.

---

## 5. Honest caveats / risks

1. **Token cost.** VS emits `k` candidates + probabilities. Reserve it for *divergent* decisions (plan/recover/ideate/evolve/synthesize), not every call. Note: it is often **cheaper** than the present ToT `1 generate + N judge` calls, because the probability is emitted inline.
2. **Probabilities are not calibrated.** Use them for ranking + tail-sampling only; keep a feasibility check (the axis VS doesn't provide). Do not surface them as confidence to users.
3. **Diversity ≠ correctness.** VS *increases* the need for a good selector/verifier. This is a feature for weebot — `RegressionGate`, `VerifyingState`, and `bash_guard` already exist; VS feeds them better-explored candidates, it does not bypass them.
4. **Latency.** Single-call VS is friendlier to the agentic loop than fan-out; reuse the existing `asyncio.gather` selection pattern.
5. **Scope discipline.** This is an *internal reasoning-diversity* upgrade. It does not change domain models, the dependency rule, or external contracts.

---

## 6. Suggested sequence (smallest risk first)

1. **ToT generation → VS** (A): one function, existing call site in `UpdatingState`, paper-backed, likely net-cheaper. Validate diversity/escape-rate on the existing ToT tests.
2. **Extract `VerbalizedSampler` + `SampledDistribution`** service once (A proves the schema).
3. **Planner candidate generation** (B/C) behind a complexity gate, reusing ToT scoring for selection.
4. **Dreamer (D)** and **Optimizer (E)** adopt the service.
5. **Synthetic held-out suite (F)** to make `RegressionGate` meaningful.

**Bottom line:** the highest-value, lowest-risk win is that weebot *already* paid for the harder half (candidate generation + scoring for recovery) using the paper's *weaker* list-level prompt. Verbalized Sampling is a measured, evidence-backed upgrade to that exact machinery, with a clean path to reuse across planning, ideation, harness evolution, and eval-data synthesis.

Related: [[code_as_harness_analysis]], [[hermes_enhancements]], [[project_architecture]].
