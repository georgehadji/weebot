# Wave 5 — LLM Adapters, Cascade & Cost

Execution record for W5 of [`tasks/specs/defect_hunt_v7_execution_plan.md`](../specs/defect_hunt_v7_execution_plan.md).
Threat **T4** (unbounded spend); classes **C4**, **C8**, **C3**, **C6**.

The plan's standing note for this wave: *cost-accounting defects are silent by construction — the
symptom is a number that reads 0.0. Proof tests must assert on the accounting, not on the call
succeeding.* Every test here does.

---

## Phase 0-WAVE

| | |
|---|---|
| **Baseline** | `5185b44`, working tree clean, all 8 CI checks green. |
| **Budget** | ≤20 generated · ≤12 investigated · ≤8 fixed |
| **Actually spent** | 8 generated · 5 investigated · 4 fixed |

---

## Phase 3/4 — triaged inventory

| ID | Claim | Trigger (3a) | Verdict |
|---|---|---|---|
| **S3** | `hasattr(resp, "usage")` is vacuous; `usage=None` makes `.get` raise | **FIRED** — `AttributeError: 'NoneType' object has no attribute 'get'` | ✅ **VERIFIED DEFECT** — reachability now confirmed |
| **D43** | `cost_estimate` never supplied ⇒ `total_cost_estimate` structurally 0.0 | **FIRED** — 0 call sites pass it | ✅ **VERIFIED DEFECT** |
| **D40** | Credit-check failure strips models; comment claims fail-open | **FIRED** — 3 models in, **1 out** | ✅ **VERIFIED DEFECT** |
| **D42** | Cache written with 4 key parts, read with 3 ⇒ `get_adapter()` never hits | **FIRED** — keys printed side by side | ✅ **VERIFIED** — but the method has **no callers**, so dead |
| **D39** | Orphaned probes on the `FIRST_COMPLETED` path keep running and billing | not triggered | 🔵 **SUSPECTED — deferred** |

### S3 — the plan's `[HYP]` on reachability is now `[VF]`

The plan recorded the mechanism as verified and reachability as hypothetical. Reachability is now
established: **four adapters set `usage = None` explicitly** —
`anthropic_adapter.py:99`, `openai_adapter.py:243` and `:351`, `caching_llm_adapter.py:132`.

The contrast is the tell, and it is the same shape as W2's four-character one:

```python
# anthropic_adapter.py:100, openai_adapter.py:244 — CORRECT
if getattr(response, "usage", None):

# _cascade.py:303 — DEFECT
getattr(resp, "usage", {}).get("total_tokens", 0) if hasattr(resp, "usage") else 0
```

`usage` is a declared dataclass field, so `hasattr` is **always** True and the `else 0` branch is
unreachable. The adapters already knew the right form.

### D40 — a comment that says the opposite of the code

```python
except Exception:
    return 0  # fail open: assume OK on API error
```

`get_credits_and_filter_direct` then tests `if credits >= threshold`. With `credits = 0` and the
default threshold of 10 000, that is **false**, so every OpenRouter-only model is filtered out.
A transient network error reaching `openrouter.ai` silently narrowed the cascade. Measured:
`["openai/gpt-4", "anthropic/claude-3", "deepseek/chat"]` → `["deepseek/chat"]`.

Fail-open is the right posture here: if credits cannot be checked, attempting the model and
letting a real 402 fall through to the next tier is exactly what a cascade is for.

### D42 — real, and dead

The write key is `provider:model:api_key:cache_flag`; the read key was `provider:model:None`.
The lookup could never hit whatever was cached. **`get_adapter()` has no callers**, so nothing
was actually harmed — fixed because a broken lookup that silently returns `None` is a trap for
the next caller, and the fix is ten lines.

---

## Phase 5 — fixes

| # | File | Change |
|---|---|---|
| 1 | `_cascade.py` | `getattr(resp, "usage", None) or {}`; token count derived from prompt+completion when `total_tokens` is absent |
| 2 | `_cascade.py` | Pass `cost_estimate=estimate_cost(model_id, prompt, completion)` — the estimator existed and had never been called |
| 3 | `_cascade.py` | `_check_openrouter_credits` returns `None` for *unknown*; the filter treats unknown as "do not filter" |
| 4 | `adapter_factory.py` | `get_adapter` matches on the `provider:model:` prefix the two keys share |

Fixes 1–3 are all inside `_cascade.py`; 1 and 2 are one edit at one call site.

### Architecture invariants (plan §6)

1 `lint-imports` 7/7 KEPT · 2 no new `ignore_imports` · 3 domain untouched · 6 no port signature
changed · 7 no Pydantic widening · 8 no new subprocess site · 10 fixes and proof tests in one
commit. All ✅.

---

## Phase 6 — six-vector self-review

| Vector | Finding |
|---|---|
| **Boundary** | `[VF]` `usage` as `None`, `{}`, and populated all pass. A model absent from the pricing table yields `0.0` without erroring — asserted, and see R-1. |
| **Invalid input** | `[VF]` `int(... or 0)` guards a `None` inside a populated usage dict. |
| **State** | `[VF]` `_check_openrouter_credits`'s return type widened to `int | None`; the only caller is `get_credits_and_filter_direct`, updated with it. |
| **Regression** | `[VF]` A genuinely low credit reading still filters; ample credits still keep everything; `get_adapter` still returns `None` for an uncached model. All asserted. |
| **Concurrency** | `[VF]` No shared state introduced. |
| **New defects** | `[HYP]` `get_adapter` now returns the first adapter matching provider+model, which may differ in api_key or caching flag from what a caller expects. Documented in the docstring; the method has no callers to be surprised. |

---

## Phase 7 — tests

`tests/unit/agents/test_w5_cascade_accounting.py`, **12 tests, new file**, driving the real
`_cascade_try_chat` with a stubbed LLM rather than asserting on source text.

**Red before, green after, verified by reverting:** the two production files stashed →
**4 failed / 8 passed**, exactly one failure per defect; restored → **12 passed**.

---

## Phase 8 — coverage & residual-risk statement

### NOT covered — stated plainly

- **D39 was not triggered.** `asyncio.wait(FIRST_COMPLETED)` leaving pending probes uncancelled
  and unawaited — models that keep running and **keep billing** — is the wave's most direct
  T4 (unbounded spend) candidate, and the one most in the spirit of the wave. It was read and
  deferred, not cleared.
- **D41** (breaker keyed on `model or self._model_name`, inspected and reset on `self._model_name`
  only) and **D44** (no client HTTP timeout on any concrete adapter; the only timeout is
  per-*attempt*, not per-call) were generated and never investigated. D44 is a T6 liveness
  candidate.
- **S2** (`parse_agent_output` never raises, so a caller cannot distinguish "the model reported
  PARTIAL" from "we failed to parse") is cross-listed to this wave from W2 and was **not**
  investigated in either.
- **The flaky stress test belongs to this wave and was not fixed.**
  `test_partial_outage_with_retries` drives a 50% failure rate off the global unseeded `random`,
  with retry delays summing to 60 s against a 30 s adapter timeout. W1–W4 each deferred it here.
  W5 did not repair it either.
- Of the six declared regions, **retry amplification** (SDK retries × `RetryWithBackoff` ×
  cascade loop) and **circuit-breaker key/state consistency** were never entered.

### Residual risks

- **R-1 — cost accounting is complete only for models in `MODEL_CASCADE`.** `estimate_cost`
  linearly scans that table and returns `0.0` for anything absent — **9 priced ids** at time of
  writing. `total_cost_estimate` is no longer *structurally* zero, but it still silently
  under-reports for any unlisted model, which is the same failure mode in a narrower form. A test
  documents the limit rather than hiding it.
- **R-2 — the credit check now fails open, by design.** If credits genuinely cannot be read while
  the account is empty, the cascade will attempt OpenRouter models and burn a timeout per model
  before falling through. That is the intended trade against silently narrowing the cascade on a
  network blip, but it converts a fast skip into a slow failure.
- **R-3 — `get_adapter`'s prefix match is ambiguous by construction** when several adapters differ
  only by api_key. No caller exists to be affected; if one is added, the ambiguity is real.

### Verdict

**PARTIAL.** Four verified defects fixed and proven, including two the plan had only hypothesised.
D39 — the wave's clearest unbounded-spend candidate — was not triggered, three more candidates
were never investigated, two of six regions were never entered, and the flaky test this wave owns
remains unfixed.
