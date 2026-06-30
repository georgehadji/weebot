# Self-Distillation (SSD) vs weebot — Value Analysis

**Paper:** *Embarrassingly Simple Self-Distillation Improves Code Generation* (Apple, arXiv:2604.01193, Apr 2026). GitHub: `apple/ml-ssd`.
**Analyzed:** 2026-06-15 against weebot @ branch `master`.
**Companion:** [verbalized_sampling_analysis.md](verbalized_sampling_analysis.md) — SSD is the *weight-level* twin of that *prompt-level* work; read both together.

---

## 1. Bottom line

The paper is a **model post-training method**. weebot is an **API-first orchestrator** that mostly consumes frontier models it cannot fine-tune. So the paper splits into three tracks of decreasing literalness and increasing certainty:

| Track | What | Works on | Effort | Certainty of payoff |
|---|---|---|---|---|
| **B — Context-typed decoding** | Apply the paper's *diagnosis* (precision-exploration conflict) as a per-call-type decoding policy | **Every model weebot uses, today** | Low | High |
| **A — Literal SSD** | Self-distill weebot's **local/open-weight tier** (Ollama/vLLM/LM Studio) on the user's own task distribution | Trainable models only | High | Medium (must be measured) |
| **D — pass@k harness** | The paper's measurement methodology; precondition for claiming A or B helped | Infra | Medium | Enabling |

**The single highest value-to-effort item is Track B.** weebot already sets a single global temperature per LLM call, hard-coded ad-hoc at each call site, and the *generative/divergent* stages are systematically under-heated. The paper gives a principled, evidence-backed framework to fix this on models weebot already uses — no training required.

**Track A is the "true to the paper" bet** and is more feasible than it first looks: weebot *already* has the data-collection half built (`TrajectoryExporter`, explicitly "for fine-tuning"), already self-improves along other axes (code/skills/strategies), and already runs a local-model tier whose success rate directly drives cost. SSD would add a *new axis*: self-improving the **model weights** with no labels, no verifier, no teacher.

---

## 2. What the paper actually says (faithful summary)

**Method (3 steps, "embarrassingly simple"):**
1. **Sample** — given a frozen base LLM and a set of prompts, draw `N` solutions per prompt at a *training* temperature `T_train` with truncation `ρ_train` (top-k/top-p). **N=1 suffices.** No execution, no test cases, no correctness filtering — only trivial syntactic cleanup (drop empties/one-line stubs).
2. **Fine-tune** — standard SFT (cross-entropy) on those raw, unverified samples.
3. **Decode** — deploy the fine-tuned model with an *evaluation* decoding config `(T_eval, ρ_eval)`.

**Results:** Qwen3-30B-Instruct 42.4% → **55.3%** pass@1 on LiveCodeBench v6 (+30% relative). Generalizes across 5 models (Llama + Qwen), 3 scales (4B–30B), instruct + thinking. **Gains concentrate on hard problems and on pass@5** (coverage), e.g. hard-problem pass@5 31.1% → 54.1%.

**Why it works — the precision-exploration conflict (the paper's real contribution):**
- Code has **lock** positions: syntax/semantics nearly determined (e.g. after `if n ==`), demanding *precision*, yet a low-probability distractor tail lingers.
- Code has **fork** positions: several genuinely plausible continuations (e.g. choosing an algorithm), demanding *exploration/diversity*.
- A **single global decoding temperature cannot satisfy both**: low `T` protects locks but starves forks; high `T` frees forks but lets distractors flood locks. The best global setting is a *compromise*.
- SSD reshapes the token distribution **context-dependently** (loss decomposition, Eq. 4): **support compression** (trims distractor tails, hardest at locks) + **within-support reshaping** (at forks keeps several continuations and flattens them into a *plateau*; at locks concentrates mass into a *spike*).
- **Effective temperature `T_eff = T_train · T_eval`** governs performance; training-time truncation adds a second gain channel (best observed: `T_train=2.0`, top-k=10, `T_eval=1.1` → 49.7%).

**Three findings that matter for weebot specifically:**
- **Decode-only tuning cannot match SSD** (§3.3, §B.5): sweeping `T_eval` on the *base* model leaves a persistent gap, because decoding can only reweight a fixed ranking — it cannot steepen locks and clean fork tails *context-dependently*. → Track B has a real ceiling; Track A breaks past it.
- **Bad data, good results** (§4.4): even near-gibberish samples (`T_train=2.0`, no truncation, ~62% non-extractable) still improved the model materially. → SSD's signal is *distributional reshaping*, not learning from correct code, so **no verifier is needed in the loop**. De-risks Track A.
- **pass@5 gains exceed pass@1**: SSD *preserves and improves* diversity rather than collapsing to one mode. → directly validates weebot's multi-candidate (fork) stages.

---

## 3. Grounded audit of weebot's current state

**3.1 Decoding is single-global and set ad-hoc.** The LLM port takes one `temperature` per call ([weebot/domain/ports.py:17](../../weebot/domain/ports.py)), and call sites hard-code values. Mapping the actual values onto the paper's lock/fork taxonomy:

| Stage | File | `T` | Paper-correct? |
|---|---|---|---|
| Verification / judging | [verifying.py](../../weebot/application/flows/states/verifying.py) (×6), [judges.py:81](../../weebot/application/eval/judges.py), [step_evaluator.py:102](../../weebot/application/services/step_evaluator.py) | 0.0 | ✅ lock → precision |
| Review / intent / CoV / failure-sig | [main_review_service.py:61](../../weebot/application/services/main_review_service.py), [chain_of_verification.py](../../weebot/application/services/chain_of_verification.py), [intent_review_service.py:54](../../weebot/application/services/intent_review_service.py) | 0.1 | ✅ lock |
| ToT recovery **generation** | [tree_of_thoughts_scorer.py:91](../../weebot/application/services/tree_of_thoughts_scorer.py) | 0.7 | ✅ fork → closest to right |
| Optimizer edit pool | [harness_opt_flow.py:345](../../weebot/application/flows/harness_opt_flow.py) | `0.3 + 0.1·edits` | ✅ already scales T for diversity — right instinct |
| **Dreamer (ideation)** | [dreamer.py:81](../../weebot/application/agents/dreamer.py) | **0.3** | ❌ the *most* fork-like stage, under-heated |
| Executor | [executor/_base.py:1185](../../weebot/application/agents/executor/_base.py) | 0.3 | ⚠️ mixed (tool-call locks + code forks) |
| Mixture-of-agents | [mixture_of_agents.py:203](../../weebot/tools/mixture_of_agents.py) | 0.3 | ⚠️ a fork ensemble, under-heated |

**Finding:** weebot's *lock* side is healthy (verification correctly pinned near 0). Its *fork* side leaves diversity on the table — ideation and ensemble stages run near precision temperatures. The paper's nuance is the key guard-rail: the fix is **not** "turn global temperature up" (that revives distractor tails at locks), it is **per-call-type decoding profiles** + truncation. Two sites (ToT, harness-opt) already show the correct instinct, unsystematized.

**3.2 The SSD data pipeline is half-built.** [trajectory_exporter.py:1-8](../../weebot/application/services/trajectory_exporter.py) already serializes sessions to JSONL and its own docstring says *"useful for creating fine-tuning datasets,"* with budget-compression support. This is exactly SSD's "collect prompts + raw outputs" stage — for weebot's *own* task distribution.

**3.3 Self-improvement exists, but only above the weights.** `MetaSelfImprover` ([meta_self_improver.py](../../weebot/application/services/meta_self_improver.py)), `evolution_tracker`, `behavioral_learner`, `skill_curator`, `retention_agent` all improve weebot's **code / strategies / skills / prompts**. None touches **model weights**. SSD is a clean *new axis* of the same self-improvement theme weebot already embraces.

**3.4 Local/open tier exists and is cost-critical.** The registry ([model_registry.py](../../weebot/config/model_registry.py)) includes Ollama (`llama3`, `phi3`), vLLM, LM Studio, HuggingFace, plus FREE OpenRouter tiers; the cascade is FREE → BUDGET → PREMIUM. Raising the local tier's success rate means more tasks resolved before escalation = direct cost win. These are exactly the *trainable* models SSD targets.

**3.5 No pass@k code-gen harness.** Grep for `pass@`/`coverage` finds test-coverage and behavior metrics, not a pass@k generation eval. weebot cannot currently *measure* whether a decoding or weight change helped on coding tasks. This is Track D.

---

## 4. Tiered opportunities

### Tier 1 — Context-typed decoding policy (Track B) · works on every model today

- **(B1) `DecodingProfile` registry.** Replace ad-hoc per-site temperatures with named, paper-grounded profiles: `LOCK` (verify/judge/structured-output/tool-call → `T≈0.0–0.2`, tight top-p), `FORK` (ideation/planning-alternatives/recovery/ensemble → `T≈0.7–1.0`, wider top-p), `MIXED` (executor → moderate). Centralize so the lock/fork intent is explicit and tunable, not scattered magic numbers.
- **(B2) Re-heat the fork stages.** Raise Dreamer (`dreamer.py:81`), Mixture-of-Agents (`mixture_of_agents.py:203`), and planner-alternative generation toward `FORK`; pair with top-p truncation so the lock-revival failure mode the paper warns about is contained. Generalize the harness-opt adaptive-temperature instinct (`harness_opt_flow.py:345`) into the registry.
- **(B3) Truncation knobs in the port.** The port exposes only `temperature`; add optional `top_p`/`top_k` pass-through (most adapters already accept them) so profiles can use truncation — the paper's *second* gain channel and the thing that lets you raise `T` at forks without flooding locks.

### Tier 2 — Literal SSD for the local tier (Track A) · the "true to the paper" capability

- **(A1) `SelfDistillationPipeline`** (new app service). Reuse `TrajectoryExporter` to harvest *prompts* from real sessions; sample N=1 per prompt from the local base model at `T_train` with truncation; minimal syntactic filter (no correctness filter — per §4.4); emit an SFT JSONL. This is the paper's recipe verbatim, fed by weebot's own usage.
- **(A2) LoRA/QLoRA fine-tune step** via an external trainer (Unsloth / Axolotl / LLaMA-Factory / TRL) on a single consumer GPU for a 4B–8B local model — far cheaper than the paper's 8×B200 full-FT. Register the adapter as a new cascade entry.
- **(A3) Agentic-trace hypothesis (weebot-specific).** weebot's structured-output + tool-call format is a strong *lock* regime; SSD on agentic traces should specifically **sharpen tool-call/JSON fidelity** (fewer malformed calls) *while preserving planning diversity at forks*. This is a concrete, testable claim that goes beyond the paper's single-shot setting — and it is exactly weebot's pain surface.
- **(A4) Tie into self-improvement.** Schedule A1–A2 as an offline job alongside `evolution_tracker`/`meta_self_improver`, gated behind a feature flag like the existing `WEEBOT_METACOGNITIVE_IMPROVEMENT`. weebot would then self-improve its weights, not just its code.

### Tier 3 — Measurement & methodology (Track D) · enabling, do this first if pursuing A

- **(D1) pass@k coding eval harness** on a small held-out task suite (`pass@1`, `pass@5`, difficulty-stratified) — mirrors the paper and fills the VS analysis's "synthetic held-out suite for RegressionGate" gap. Without it, Track A/B improvements are unprovable.
- **(D2) `T_train × T_eval` mini-sweep** when running A, to find weebot's `T_eff` sweet spot rather than copying the paper's competitive-programming numbers.

---

## 5. Relationship to Verbalized Sampling (last session)

SSD and VS attack the **same disease** (mode collapse / precision-exploration tension) at **different layers**, and compose cleanly:

- **VS = prompt layer.** Ask for `k` candidates with verbalized probabilities. Works on any API model, zero training. Recovers fork diversity *at inference*.
- **SSD = weight layer.** Reshape the distribution so locks are sharp and forks stay diverse *intrinsically*. Trainable models only, but yields gains **no prompt or decoding policy can replicate** (§B.5).
- **Unifying lens = pass@k.** Both are validated by "diversity at forks cracks hard problems." weebot's fork stages (ToT, planner, dreamer, MoA, debate) are pass@k machines: VS generates better candidates, Track B decodes them at the right temperature, SSD makes the base model produce *useful* (not distractor) diversity. Track D measures all three.

---

## 6. Honest caveats / what NOT to do

- **Don't expect frontier API gains.** Literal SSD only helps *trainable* models. The Claude/GPT/Gemini path weebot prefers is untouched by Track A (and you can't fine-tune them). Track A's value is concentrated in the **local/free tier**.
- **Distribution mismatch is real.** SSD was validated on *single-shot competitive programming*. weebot does *multi-turn agentic tool-use*. The gains are a **hypothesis to measure (Track D), not a guarantee** to copy. Build the harness before claiming a win.
- **Don't globally raise temperature.** The paper's whole point is that a single global setting is the problem; a naive `T` bump re-floods locks with distractors. Use *typed* profiles + truncation (B1/B3).
- **Don't add a verifier to the SSD loop.** §4.4 shows it's unnecessary and the paper's gains survive bad data; adding filtering reintroduces the "needs execution/labels" cost SSD was designed to avoid.
- **Training infra is the real cost of Track A.** A LoRA trainer dependency, a GPU, and an eval loop are a genuine project — sequence it after Track B + Track D prove the measurement and the cheap win.

---

## 7. Suggested sequence

1. **Track D (D1)** — stand up a small pass@k harness. (Unblocks everything; small.)
2. **Track B (B1–B3)** — decoding-profile registry + re-heat forks + truncation knobs. (Cheapest, broadest, immediate.)
3. Measure B with D. If positive, **Track A (A1)** — SSD data pipeline off `TrajectoryExporter`; then A2 LoRA on one local model; validate the A3 tool-call-fidelity hypothesis with D.

**Net:** Track B is a near-free, evidence-backed win on every model weebot runs today. Track A is a deeper bet that turns weebot's existing trajectory-export + self-improvement machinery into genuine weight-level self-improvement for self-hosters — exactly the paper's promise, scoped to where weebot can actually train.
