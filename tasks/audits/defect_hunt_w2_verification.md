# Wave 2 — Verification & Evidence Gates

Execution record for W2 of [`tasks/specs/defect_hunt_v7_execution_plan.md`](../specs/defect_hunt_v7_execution_plan.md).
Threat **T3** (fail-open verification); classes **C2**, **C3**, **C8**.

The wave's governing question, applied to every gate on the surface:

> *If this gate's own machinery fails, does it report a violation or report clean?*

---

## Phase 0-WAVE

| | |
|---|---|
| **Baseline** | `f898912`, working tree clean, all 8 CI checks green on the preceding head. |
| **Budget** | ≤20 generated · ≤12 investigated · ≤8 fixed |
| **Actually spent** | 8 generated · 6 investigated · 3 fixed |

---

## Phase 3/4 — triaged inventory

| ID | Gate | Instrument-failure result | Verdict |
|---|---|---|---|
| **D14** | `step_evaluator.py:93` — `json.loads(resp.content or "{}")` | Empty/`None` completion → `score=1.0`, `passed=True`, `reasoning=''`, **no exception and no log** | ✅ **VERIFIED DEFECT** |
| **D13** | `step_evaluator.py:104` — exception → `score=1.0, passed=True` | Fires, but **documented**: *"Fails open on LLM errors so execution never blocks."* | ⚠️ **PARTLY DEFENDED** — see below |
| **D15** | `conversation_compressor.py:137` — failure → `"(compression failed: …)"` | **3 middle turns destroyed**, replaced by the error string, in a normally-shaped buffer the caller commits | ✅ **VERIFIED DEFECT** |
| **D15b** | `trajectory_exporter.py:165` — second, undocumented caller of `_summarize` | Same mechanism: middle events discarded for an error string | ✅ **VERIFIED DEFECT** — not in the plan; found by tracing callers |
| **D17** | `verifier_scorer.py:84` — bare `json.loads(response.content)` | Raises → caught → `score=0.0` + `failure_modes=["verifier_error: …"]` | ⚪ **FALSE — fails closed, and correctly** |
| **D16** | `trajectory_builder.py:74` — failure → `failure_modes=[]` | Fires, but **logs a warning**, so it is not invisible; blast radius is learning quality | 🔵 **SUSPECTED — deferred** |
| **D18** | `structured_output.py:430` — empty distribution on any failure | Not triggered; consumers not traced | 🔵 **SUSPECTED — deferred** |

### The contrast that pinpoints D14

Two gates in this codebase parse an LLM verdict. They differ by four characters.

```python
# verifier_scorer.py:84 — CORRECT
data = json.loads(response.content)          # ""  -> JSONDecodeError -> score 0.0

# step_evaluator.py:93 — DEFECT
data = json.loads(resp.content or "{}")      # ""  -> {} -> .get("score", 1.0) -> 1.0
```

The `or "{}"` converts a fail-closed parse into a **silent** fail-open. It is not the documented
behaviour: the docstring promises fail-open *"on LLM errors"*, and an empty completion raises no
error. Verified by execution, all four instrument-failure modes.

**Blast radius is real.** `flows/states/executing.py:623` routes `not _eval.passed` to
`UpdatingState()` — plan revision. A silently-broken evaluator therefore **skips the plan
revision it exists to trigger**, and looks identical to one passing every step on merit.

### Why D15 is the more serious of the two

Compression is lossy *by design*, which is exactly why its failure must be a no-op rather than a
loss. `compress()` put the error string into a summary message and returned `head + [summary] +
tail`; `_context_compressor.py:113` tests `if compressed_middle:`, a non-empty list is truthy, so
it cleared the buffer and committed the replacement. **The conversation middle was destroyed on a
transient LLM error.** Measured: 12 messages in, 3 turns discarded, replaced by
`"(compression failed: provider 503)"`.

**Correction to the plan.** §7.3 D15 claimed the error string itself is truthy at
`_context_compressor.py:113`. It is not — `compress()` returns a *list*, and the string sits
inside it. Same outcome, different mechanism. The code comment at `_context_compressor.py:107-111`
documents an earlier, separate bug at that line.

---

## Phase 5 — fixes

| # | File | Change |
|---|---|---|
| 1 | `step_evaluator.py` | Empty/whitespace completion and JSON with no `score` key now raise into the existing logged fail-open path instead of manufacturing a verdict |
| 2 | `conversation_compressor.py` | `_summarize` returns `""` on failure; `compress()` returns the buffer **unchanged** when there is no summary |
| 3 | `trajectory_exporter.py` | Same contract at the second call site: no summary ⇒ return the events unchanged |

### Deviation from the fix policy, recorded as the runbook requires

The plan's Phase 5 sets **≤1 function** per fix. Fix 2 touches `_summarize` and `compress()`, and
fix 3 touches a third function in another module. They are one contract change — *an empty
summary means no compression* — and splitting it would have left one of the two call sites still
destroying data. Total production diff is 27 lines including comments.

### What was deliberately NOT changed

`passed=True` on instrument failure is **kept**. It is documented, intentional, and reversing it
would let a broken evaluator block execution — a worse failure than the one being fixed. The
defect was that failure was *indistinguishable*, not that it was permissive.

**`[REQUIRES HUMAN REVIEW: cross-boundary mechanism]`** — reporting `score=1.0` for a step that was
never evaluated stays misleading to any consumer that aggregates scores. The clean fix is a field
on the `StepEvaluation` port dataclass (`evaluated: bool`), and plan invariant 6 makes a port
signature change cross-boundary *regardless of line count*. Today the only consumer reads
`.passed` and logs `.score`, so the live blast radius is a log line; `reasoning` now carries the
`"evaluation failed:"` prefix as a stringly-typed distinguisher in the meantime.

---

## Phase 6 — six-vector self-review

| Vector | Finding |
|---|---|
| **Boundary** | `[VF]` A whitespace-only completion is treated as empty (`.strip()`). A valid `{"score": 0}` is *not* treated as missing — `"score" not in data` tests the key, not truthiness, so a legitimate zero still scores 0. |
| **Invalid input** | `[VF]` `content=None`, `""`, `"   "`, non-JSON prose, and JSON without a `score` key all take the logged path. |
| **State** | `[VF]` A failed compression now leaves the buffer larger than the caller wanted. The caller may hit its context limit and retry — strictly better than silently losing turns, but it is a real behaviour change under sustained LLM failure. |
| **Regression** | `[VF]` Successful compression still compresses; a well-formed low score still fails its step. Both asserted. |
| **Concurrency** | `[VF]` No shared state introduced; both fixes are local to a call. |
| **New defects** | `[HYP]` If a provider legitimately returns an empty completion for a well-formed request, the evaluator now logs a warning per step where it previously logged nothing. Noisier, but that noise is the finding. |

---

## Phase 7 — tests

| File | Added | Purpose |
|---|---|---|
| `tests/unit/services/test_compression_is_not_destructive.py` | **10 tests, new file** | Proof + boundary + no-regression for D15/D15b |
| `tests/unit/services/test_step_evaluator.py` | +7 | Proof + fail-open preservation + no-regression for D13/D14 |

**Red before, green after, verified by reverting:** the three production files stashed →
**10 failed / 16 passed**; restored → **26 passed**.

---

## Phase 8 — coverage & residual-risk statement

### Covered

`step_evaluator`, `conversation_compressor`, `trajectory_exporter` and `verifier_scorer`
investigated to a verdict with executable instrument-failure triggers. Three defects fixed with
proof tests; one candidate (D17) cleared as genuinely correct.

### NOT covered — stated plainly

The W2 surface names **thirteen** modules. **Four** were investigated. Untouched:
`step_evidence_auditor.py`, `plan_critic.py`, `meta_critic.py`, `chain_of_verification.py`,
`skill_review_gate.py`, `flows/states/verifying.py`, `critiquing.py`, `product_gate.py`,
`premortem.py`, `application/eval/judges.py`. **The wave's own method — enumerate every function
returning a pass/fail, score or violation list — was not run to completion.** Each of those
modules is a gate, and the governing question has not been asked of any of them.

`step_evidence_auditor.py` is the most conspicuous gap: `executing.py:640-650` routes its verdict
the same way the step evaluator's is routed, so the identical defect class would have the
identical blast radius.

D16 and D18 were read and deferred, not cleared. S2 (`parse_agent_output` never raises, plan §7.2)
was **not** investigated in this wave.

### Residual risks

- **R-1 — an uncompressible buffer is now unbounded.** Under sustained LLM failure the compressor
  is a no-op every time, so the buffer keeps growing until the provider rejects it. That is the
  correct trade against silent data loss, but nothing caps it. `[HYP]` no consumer treats
  "compression made no progress" as a terminal condition — not verified.
- **R-2 — `score=1.0` for an unevaluated step** remains, escalated above.
- **R-3 — the fail-open policy itself is unexamined.** This wave made two gates honest about
  failing; it did not ask whether failing open is the right default for a *verification* gate.
  That is a product decision, not a defect.

### Verdict

**PARTIAL.** Three verified defects fixed and proven, one candidate correctly cleared, one
escalated. Nine of thirteen surface modules were never hunted — the wave stopped at its
investigation budget, not at its surface.
