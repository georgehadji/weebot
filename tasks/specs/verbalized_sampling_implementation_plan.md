# Verbalized Sampling — Implementation Plan

**Source analysis:** [verbalized_sampling_analysis.md](verbalized_sampling_analysis.md)
**Paper:** Zhang, Yu, Chong et al., *Verbalized Sampling* (arXiv:2510.01171v3, Oct 2025)
**Drafted:** 2026-06-15 · branch `master`
**Scope:** All enhancements (A→H). Phased, flag-gated, each phase independently shippable and reversible.

> **Guiding principle.** VS is *pure prompting + a structured-output schema*. It requires **no `LLMPort` change** and no new external dependency. One shared service is built once (Phase 0); every consumer reuses it. Diversity is opt-in for *divergent* decisions only (plan / recover / ideate / evolve / synthesize); convergent execution and tool-argument generation are never wrapped.

---

## 0. Cross-cutting decisions (apply to every phase)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Output schema | **JSON** `{"responses":[{"text","probability"}...]}` (not the paper's XML `<response>` tags) | Matches weebot's universal `response_format={"type":"json_object"}` + existing parsers |
| Probability semantics | **Steering/selection signal only — never surfaced as confidence** | Paper §7 itself scores answer *frequency*, not verbalized numbers |
| Model tier | Route VS calls to a **capable** model (`MODEL_VS_CAPABLE` = Tier-4 `qwen/qwen3.7-max`, fallback Grok 4.3) | Paper's emergent trend: larger models benefit more; VS is wasted on FREE tier |
| Temperature | `TEMPERATURE_CREATIVE` (0.7) default, configurable | Paper: VS is *orthogonal* to temperature and stacks with it |
| Failure mode | **Fail-open**: any parse/LLM error → single-item distribution wrapping a direct call | Never regress availability of the agentic loop |
| Selection | VS *generates*; existing selectors (ToT scorer, merge/rank, RegressionGate) *choose*. Diversity never bypasses verification | Diversity ≠ correctness |
| Rollout | Every consumer behind a `VS_ENABLE_*` flag defaulting **off**, flipped on per-phase after its diversity test passes | Safe incremental adoption |

**Observability:** every VS call emits a `verbalized_sample` span via the existing `workflow_tracer` with `{k, threshold, variant, returned_count, mode_prob, selected_strategy, model}` so we can audit diversity in production.

---

## Phase 0 — Foundation: `VerbalizedSampler` service + `SampledDistribution` model

**Goal:** one reusable, tested primitive. No behaviour change anywhere yet.

### 0.1 Structured-output models — append to `weebot/models/structured_output.py`
Honors the Structured Output Protocol (CLAUDE.md rule 2).

```python
class SampledResponse(BaseModel):
    """One candidate from a verbalized distribution."""
    text: str = Field(..., description="Candidate response text or JSON payload")
    probability: float = Field(
        ..., ge=0.0, le=1.0,
        description="Verbalized probability. STEERING SIGNAL ONLY — not calibrated confidence.",
    )

    @field_validator("probability", mode="before")
    @classmethod
    def _coerce_prob(cls, v):  # tolerate "0.12", "12%", 12 → 0.12
        ...

class SampledDistribution(BaseModel):
    """A verbalized distribution over candidate responses."""
    responses: list[SampledResponse] = Field(default_factory=list)

    def mode(self) -> SampledResponse | None: ...                 # argmax probability
    def weighted_sample(self, rng: random.Random) -> SampledResponse | None: ...
    def tail(self, threshold: float) -> list[SampledResponse]: ... # prob < threshold (novelty)
    def texts(self) -> list[str]: ...

def parse_sampled_distribution(raw_text: str) -> SampledDistribution:
    """Reuse the existing markdown/brace-extraction logic from parse_agent_output;
    return an empty distribution (never raises) so the service can fail open."""
```

### 0.2 Service — new `weebot/application/services/verbalized_sampler.py`
```python
class VerbalizedSampler:
    def __init__(self, llm: LLMPort, model: str | None = None,
                 default_k: int = VS_DEFAULT_K) -> None: ...

    async def sample(
        self, instruction: str, *,
        k: int | None = None,
        threshold: float | None = None,     # None = full distribution; else tail clause
        variant: Literal["standard", "cot"] = "standard",
        context: str = "",
        temperature: float = TEMPERATURE_CREATIVE,
        max_tokens: int = MAX_TOKENS_STANDARD,
        timeout: float = 20.0,
    ) -> SampledDistribution:
        """Build the VS prompt, call llm.chat(response_format=json_object),
        parse → SampledDistribution. Fail-open to a 1-item distribution."""
```
- Builds messages from the prompt template (0.3); `variant="cot"` prepends a "reason first, then output the distribution" instruction (paper's VS-CoT — best on capable models).
- Routes to `self._model or MODEL_VS_CAPABLE`.
- Wrapped in `asyncio.wait_for`; on any exception logs at WARNING and returns `SampledDistribution(responses=[SampledResponse(text=<direct fallback>, probability=1.0)])`.

### 0.3 Prompt template — new `weebot/config/prompts/verbalized_sampling.txt`
Loaded via existing `load_prompt_with_fallback`. Adapted from paper Figure 2 to JSON:
```
You are a helpful assistant. For the given task, generate a set of {k} DISTINCT
candidate responses that together approximate the full distribution of good answers.

Return ONLY valid JSON, no markdown:
{"responses": [{"text": "<candidate>", "probability": <0..1>}, ...]}

- Each candidate must be meaningfully different from the others.
- "probability" is your estimate of how typical/likely each candidate is.
{threshold_clause}
```
`{threshold_clause}` is empty for the full distribution, or (tail mode):
`- Favor the TAILS: only include candidates whose probability is below {threshold}.`

### 0.4 Config — `weebot/config/constants.py` and `weebot/config/model_refs.py`
- `constants.py`: `VS_DEFAULT_K = 5`, `VS_TAIL_THRESHOLD = 0.10`, and flags
  `VS_ENABLE_RECOVERY/PLANNING/DREAMER/OPTIMIZER/CONTENT = False` (env-overridable).
- `model_refs.py`: `MODEL_VS_CAPABLE = MODEL_CASCADE_TIER4` (`qwen/qwen3.7-max`) +
  `def get_vs_model() -> str` returning it (single source of truth for the capable tier).

### 0.5 Tests — `tests/unit/test_verbalized_sampler.py`
- Parsing: clean JSON, fenced JSON, trailing prose, `"12%"`/`12` coercion, malformed → empty.
- Selection: `mode` argmax, `tail(0.1)` filter, `weighted_sample` determinism under seeded RNG.
- Fail-open: LLM raises / times out → 1-item distribution, no exception.
- Prompt build: `k`, threshold clause, `cot` variant injection.

**DoD:** service importable, 100% of the above tests green, zero changes to runtime behaviour (flags off).

---

## Phase 1 — (A) ToT failure-recovery generation → VS  *[lowest risk; do first]*

**Why first:** the seam already exists ([updating.py:49](../../weebot/application/flows/states/updating.py)) and the current generator is the paper's *weaker* list-level prompt ([tree_of_thoughts_scorer.py:69](../../weebot/application/services/tree_of_thoughts_scorer.py)). Evidence-backed upgrade, likely **net-cheaper**.

### Changes — `weebot/application/services/tree_of_thoughts_scorer.py`
- `__init__` gains optional `sampler: VerbalizedSampler | None`.
- `generate_candidates`: when `VS_ENABLE_RECOVERY` and a sampler is present, call
  `sampler.sample(instruction=<failed step + "produce replacement approaches">, k=num_candidates, threshold=VS_TAIL_THRESHOLD, variant="cot", context=failure_context)` and return `dist.texts()`. Else keep the current list-level path verbatim (fallback).
- `best_candidate`: keep the feasibility/specificity LLM judge (the axes VS does **not** provide); the VS `probability` supplies the **novelty prior**, so we can drop the separate novelty re-scoring → fewer judge calls. Selection becomes `feasibility × specificity`, tie-broken by inverse typicality (tail = more novel).

### Wiring — `weebot/application/flows/states/updating.py`
Construct the sampler next to the scorer:
```python
from weebot.application.services.verbalized_sampler import VerbalizedSampler
tot = TreeOfThoughtsScorer(llm=context._llm,
                           sampler=VerbalizedSampler(llm=context._llm))
```

### Tests
- `tests/unit/test_tree_of_thoughts.py`: extend — with `VS_ENABLE_RECOVERY=True` and a stub sampler returning a 3-item distribution, `best_candidate` selects the highest feasibility×specificity; flag off → legacy path unchanged.
- Diversity regression (see §9): VS candidates score higher pairwise-distinct than the legacy list prompt on a fixed failure fixture.

**DoD:** existing ToT tests pass with flag off; new tests pass with flag on; diversity metric ↑ on the fixture; flip `VS_ENABLE_RECOVERY=True`.

---

## Phase 2 — (B) Multi-candidate `create_plan` + (C) tail-sampled `update_plan`

**Goal:** stop collapsing planning to one stereotyped decomposition (currently temp `0.0`, single plan — [planner.py:247](../../weebot/application/agents/planner.py)).

### 2B — `create_plan` candidate generation + selection
- `PlannerAgent.__init__` gains optional `sampler` + `plan_selector`.
- New private `_generate_plan_candidates(user_msg) -> list[Plan]`: when `VS_ENABLE_PLANNING`, VS-sample `k=3` candidate **plans** (each candidate's `text` is a full plan JSON), parse each via the existing `_parse_plan`. Else single-shot (current behaviour).
- **Selection (reuse, don't reinvent):** score candidates with the ToT scorer's feasibility/specificity axes (or the existing `plan_critic` / `ConfidentThresholds` already invoked in `UpdatingState`). Pick the best; keep the others in `_plan_history` for novelty tracking.
- **Complexity gate:** only multi-sample when the task looks non-trivial (≥3 anticipated steps / matches the planner's existing multi-section heuristics). Trivial tasks stay single-shot → no cost regression.

### 2C — `update_plan` principled tail-sampling
- Replace the brittle natural-language *"Do NOT attempt the same command or pattern"* ([planner.py:276](../../weebot/application/agents/planner.py)) and the `PlanNoveltyTracker.avoidance_prompt` fallback ([updating.py:142](../../weebot/application/flows/states/updating.py)) with a VS **tail** sample of recovery strategies (`threshold=VS_TAIL_THRESHOLD`) — the distribution-grounded version of "do something different."
- Keep `PlanNoveltyTracker` as the *measurement* of whether novelty actually increased (telemetry), not as the prompt hack.

### CQRS note
`UpdatePlanCommand` path ([updating.py:86](../../weebot/application/flows/states/updating.py)) is unchanged structurally; the diversification happens inside the planner/handler so pipeline behaviours (logging/validation/telemetry) still fire.

### Tests
- `tests/unit/test_planner.py`: stub sampler → 3 candidate plans; selector picks best; flag off → single plan path identical. Complexity gate: trivial prompt → 1 sample; complex prompt → k samples.
- Integration: a flow run where the first plan is deliberately weak; assert the selected plan differs and scores higher.

**DoD:** planner unit + flow integration tests green both flag states; diversity/quality metric on a planning fixture set shows ↑ coverage with no quality drop; flip `VS_ENABLE_PLANNING=True`.

---

## Phase 3 — (D) Dreamer ideation via VS-CoT

**Goal:** the Dreamer's whole job is divergent ideation — most directly hit by collapse ([dreamer.py:74](../../weebot/application/agents/dreamer.py)).

### Changes — `weebot/application/agents/dreamer.py`
- Inject `VerbalizedSampler`; under `VS_ENABLE_DREAMER`, replace the single list-prompt call with `sampler.sample(instruction=<signals → ideas>, k=max_contracts, threshold=VS_TAIL_THRESHOLD, variant="cot", context=signal_block)`.
- Map each `SampledResponse` → `IdeaContract`. Redefine `heat_score = urgency × (1 − probability) × confidence` — *inverse* verbalized typicality becomes the **novelty** term (tail ideas score hotter), replacing the hand-rolled novelty guess.
- Keep the `_MAX_CONTRACTS` cap and fail-open `[]` contract.

### Tests
- `tests/unit/test_dreamer.py`: stub sampler distribution → contracts sorted by recomputed heat; low-probability (tail) idea ranks above a high-probability one at equal urgency/confidence; sampler failure → `[]`.

**DoD:** dreamer tests green; on a fixed signal fixture, mean pairwise distinctness of surfaced ideas ↑ vs legacy; flip `VS_ENABLE_DREAMER=True`.

---

## Phase 4 — (E) Evolution-Agent edit-pool diversification

**Goal:** stop harness self-improvement converging to a local optimum. `reflect_on_*` generates the candidate `SkillEdit` pool that `merge_edits`/`rank_edits` prune ([optimizer_agent.py:51](../../weebot/application/agents/optimizer_agent.py)).

### Changes — `weebot/application/agents/optimizer_agent.py`
- `_reflect_minibatch`: under `VS_ENABLE_OPTIMIZER`, generate edits through VS (`k` distinct edit-sets with probabilities, tail-weighted) instead of one reflection completion, then flatten into the candidate pool **before** the existing 3-stage `merge_edits` and `rank_edits`. The governance pipeline (merge → rank → `RegressionGate`) is the selector and is unchanged — we only widen the input pool.
- Guard cost: VS only on the reflection step, not on merge/rank (those stay `TEMPERATURE_PRECISE`).

### Tests
- `tests/unit/test_optimizer_agent.py` (or existing harness tests): stub sampler → diverse edits; assert the merged pool contains a tail edit that the legacy single-reflection path missed; `rank_edits` still clips to budget.

**DoD:** optimizer/harness tests green both flag states; on a fixed trajectory batch, candidate-pool distinctness ↑ with no drop in post-`RegressionGate` acceptance quality; flip `VS_ENABLE_OPTIMIZER=True`.

---

## Phase 5 — (F) Synthetic held-out regression/eval suite generator

**Goal:** make `RegressionGate` meaningful. Infra exists (held-in/held-out, `min_held_out_tasks` — [cli/commands/harness.py:193](../../cli/commands/harness.py)) but needs a *diverse* task suite. Paper §8: VS synthetic data is more diverse → better downstream metrics.

### New — `weebot/application/services/eval_suite_generator.py`
- `async def generate_suite(domain_seeds: list[str], n: int, k: int = 5) -> list[EvalTask]`: VS-sample diverse task prompts + expected-outcome rubrics across the seed domains (the paper's `N` total across `⌈N/k⌉` calls), dedup by embedding/lexical distance, persist as held-out tasks.
- Each generated task carries provenance (`source="vs_synthetic"`, generator model, seed) for auditability.

### CLI — extend `cli/commands/harness.py`
- `weebot harness gen-eval --domain <seed> --n 50 --out tasks/eval/held_out.jsonl` → writes a suite consumable by the existing `--held-out-tasks` flow.

### Tests
- `tests/unit/test_eval_suite_generator.py`: stub sampler → N tasks, dedup removes near-duplicates, provenance attached, suite count ≥ `min_held_out_tasks`.

**DoD:** generator + CLI tested; a generated suite passes `RegressionGate` schema; distinct-n of generated tasks ≫ a hand-written baseline. (No runtime flag — opt-in CLI tool.)

---

## Phase 6 — (G) Creative / content interfaces

**Goal:** apply VS where the paper is strongest (creative writing, 1.6–2.1×) and operationally enforce the user's **anti-template / anti-AI-slop** web rules.

### Targets
- Copy/headline/CTA generation in website + portfolio skills, and `examples/linkedin_post.py`.
- Under `VS_ENABLE_CONTENT`, route copy generation through `VerbalizedSampler` (full distribution, `variant="cot"`), then either present the top-N variants to the user or auto-select the mode while keeping alternates.

### Tests
- Snapshot/diversity test on a fixed brief: generated variants exceed a distinct-n floor; mode variant still passes the existing quality/length constraints.

**DoD:** content paths produce ≥N distinct on-brief variants; flip `VS_ENABLE_CONTENT=True` for the relevant skills.

---

## Phase 7 — (H) VS as a cheaper first tier vs Mixture-of-Agents

**Goal:** offer single-call intra-model diversity before paying for N-provider MoA. **Complement, not replacement** (MoA's value is cross-*model* diversity VS can't replicate).

### Changes — `weebot/tools/mixture_of_agents.py`
- Add a `diversity_mode: Literal["intra","inter"] = "inter"` parameter. `"intra"` → one VS call on the capable model feeds the existing aggregator (`_aggregate` unchanged); `"inter"` → current multi-model behaviour.
- Document when to choose which (intra = cheap exploration; inter = genuine cross-model disagreement).

### Tests
- `tests/unit/test_mixture_of_agents.py`: `"intra"` path issues one VS call + one aggregator call; `"inter"` path unchanged.

**DoD:** both modes tested; intra mode measurably fewer provider calls; default stays `"inter"`.

---

## 8. DI / wiring summary

- Register a shared `VerbalizedSampler` factory in `weebot/application/di.py` (uses the role/cascade LLM adapter, `model=get_vs_model()`), injected into Planner, Dreamer, Optimizer, and the ToT scorer. States that construct helpers inline (`UpdatingState`) build it from `context._llm` — matching the current ToT construction pattern.
- No `LLMPort`, domain-model, or external-contract changes. Dependency rule preserved (service lives in Application, depends only inward on the port + domain models).

## 9. Diversity measurement harness (proves each phase works)

Add `tests/util/diversity_meter.py`:
- `distinct_n(texts, n=2)` — lexical diversity, dependency-free (paper's Distinct-N).
- Optional `semantic_diversity(texts)` = `1 − mean_pairwise_cosine` if an embedding/rerank model is already configured (paper's metric); else skip.
- Each phase's "diversity regression" test asserts `distinct_2(vs_outputs) > distinct_2(legacy_outputs)` on a frozen fixture, and a **quality guard** asserting the selected output still passes that consumer's existing validation (mirrors the paper's "precision ≈ 1.0" — diversity must not cost correctness).

## 10. Sequencing, risk, rollback

| Phase | Risk | Rollback |
|-------|------|----------|
| 0 Foundation | none (no behaviour) | delete service/flag |
| 1 ToT recovery | low — flagged, fail-open, net-cheaper | `VS_ENABLE_RECOVERY=False` |
| 2 Planning | med — touches core loop; gated by complexity check | `VS_ENABLE_PLANNING=False` |
| 3 Dreamer | low — fail-open `[]` | `VS_ENABLE_DREAMER=False` |
| 4 Optimizer | med — affects self-improvement; selector unchanged | `VS_ENABLE_OPTIMIZER=False` |
| 5 Eval suite | low — offline CLI | don't run it |
| 6 Content | low — variant selection | `VS_ENABLE_CONTENT=False` |
| 7 MoA mode | low — opt-in param, default unchanged | use `"inter"` |

**Order:** 0 → 1 → 2 → 3 → 4 → 5 → (6, 7 any time). Ship one phase per PR; flip its flag only after its diversity + quality-guard tests are green.

## 11. Definition of done (overall)

- `VerbalizedSampler` + `SampledDistribution` shipped, 100% unit-tested, fail-open.
- Each consumer phase: legacy path byte-identical with flag off; VS path green with flag on; diversity ↑ and quality guard holds on a frozen fixture.
- Telemetry span `verbalized_sample` visible in `workflow_tracer`.
- Verbalized probabilities never surfaced to users as confidence.
- Docs: short `docs/verbalized-sampling.md` (what/why/flags), and update CLAUDE.md design-patterns note if Planner behaviour changes default.

Related: [[verbalized_sampling_analysis]] · [[code_as_harness_analysis]] · [[hermes_enhancements]] · [[project_architecture]]
