# Plan: Single-Source-of-Truth Remediation for Constants, Models & Magic Numbers

**Status:** DRAFT — not started
**Date:** 2026-06-17
**Author:** audit follow-up (see conversation: hardcoded-values audit)
**Scope:** `weebot/`, `cli/`, `tests/` (`.py` only)

---

## 1. Goal

Eliminate single-source-of-truth (SSOT) violations where hardcoded LLM model
strings, temperatures, `max_tokens`, and message-role literals are duplicated
across source files instead of referencing the canonical definitions that
**already exist** in:

- `weebot/config/model_refs.py` — canonical model IDs + role cascades
- `weebot/config/constants.py` — `TEMPERATURE_*`, `MAX_TOKENS_*`, limits
- `weebot/config/settings.py` — env-backed `TEMPERATURE`, `MAX_RETRIES`, etc.

The canonical files are good. The problem is **call sites that bypass them**.

---

## 2. Findings Recap (what we are fixing)

| Tier | Problem | Severity | Count |
|------|---------|----------|-------|
| A | Production code hardcodes a model string not in `model_refs.py` | HIGH | 1 real site |
| B | `temperature=` / `max_tokens=` literals at LLM call sites | MEDIUM | 49 across 21 files |
| C | Message-role literals `"system"/"user"/"assistant"` not centralized | LOW | ~8 files |
| D | Tests assert vision logic against stale `"claude-opus-4-8"` literal | LOW (hygiene) | 15 occurrences |

**Explicitly NOT violations (leave alone):**
- `weebot/utils/cost_ledger.py:57,61` — pricing table *keyed by* model name; the
  literal IS the canonical key. Line 49 is a docstring example.
- `model_aware_harness_resolver.py:20` — docstring usage example, not code.
- `model_registry.py` / `model_selection.py` model literals — these files ARE
  the registry; literals are definitions, not duplications.
- `moonshot_adapter.py` `temperature=1.0` — hard provider requirement for Kimi;
  already documented and has `TEMPERATURE_KIMI` if we want to reference it.

---

## 3. Phase A — Production model-string violation (HIGH, do first)

### A.1 Add the missing canonical constant
`gpt-4o-mini` is used in production but absent from `model_refs.py`. It exists in
`model_registry.py` and `model_selection.py`, but those are not the short-name
export surface. Decide the intent:

- If `flow_undo` genuinely wants the cheapest utility model, it should use the
  **existing** budget constant rather than a new one. The current codebase's
  cheap default is `MODEL_BUDGET = "x-ai/grok-build-0.1"` (or
  `MODEL_COMMAND_DEFAULT = "minimax/minimax-m3"` for CQRS-style commands).

**Recommended:** route `flow_undo` through the command default, since undo is a
lightweight CQRS-style operation:

```python
# cli/commands/flow.py
from weebot.config.model_refs import MODEL_COMMAND_DEFAULT
...
llm = model_service.create_llm_adapter(MODEL_COMMAND_DEFAULT)
```

### A.2 If `gpt-4o-mini` specifically is still required elsewhere
Only if a real OpenAI `gpt-4o-mini` dependency must be pinned, add an explicit
constant to `model_refs.py` so it is named once:

```python
MODEL_UTILITY_OPENAI: str = "openai/gpt-4o-mini"
"""Cheap OpenAI utility model — undo/CQRS-style lightweight ops."""
```

**Files touched:** `cli/commands/flow.py` (line 140); optionally `model_refs.py`.
**Verification:** `python -m cli.main flow run` smoke + `pytest tests/ -k flow`.
**Decision needed:** route to existing budget constant (preferred) vs. pin a new
`gpt-4o-mini` constant. → ask before implementing.

---

## 4. Phase B — Temperature & max_tokens literals (MEDIUM, the bulk)

### B.1 Map every literal to an existing constant

`constants.py` already defines the semantic presets. Apply this mapping:

**Temperature:**

| Literal | Constant | Notes |
|---------|----------|-------|
| `0.0` / `0` | `TEMPERATURE_DETERMINISTIC` | |
| `0.1` | `TEMPERATURE_PRECISE` | |
| `0.2` | `TEMPERATURE` (from settings) | general default |
| `0.3` | `TEMPERATURE_BALANCED` | |
| `0.7` | `TEMPERATURE_CREATIVE` | |
| `0.4` | **NO CONSTANT** — see B.2 | premortem only |
| `1.0` | `TEMPERATURE_KIMI` | provider-forced, leave or reference |

**max_tokens:**

| Literal | Constant | Notes |
|---------|----------|-------|
| `256` | `MAX_TOKENS_COMPACT` | |
| `300` | `MAX_TOKENS_CONCISE` | |
| `500` | `MAX_TOKENS_SHORT` | |
| `1000` | `MAX_TOKENS_MODERATE` | |
| `2000` | `MAX_TOKENS_STANDARD` | |
| `2048` | `MAX_TOKENS_EXTENDED` | |
| `128` | `MAX_TOKENS_TINY` | |
| `5,10,100,150,200,512,800,900` | **NO CONSTANT** — see B.2 | |

### B.2 Decide policy for literals with no matching constant
Several call sites use values with no preset: temps `0.4`; tokens
`5, 10, 100, 150, 200, 512, 800, 900`. Options per value:

1. **Round to the nearest existing preset** (preferred where behavior is not
   sensitive) — e.g. `max_tokens=512` → `MAX_TOKENS_SHORT` (500),
   `max_tokens=200` → `MAX_TOKENS_COMPACT` (256 — *increases* cap, verify ok).
2. **Add a new named constant** when the value is semantically meaningful and
   intentionally tight — e.g. `max_tokens=5` / `=10` are deliberate
   single-token-ish gates (yes/no verdicts in `verifying.py:436`,
   `model_health.py:38`). These deserve names like:
   ```python
   MAX_TOKENS_VERDICT: int = 10   # yes/no or score-only gate responses
   MAX_TOKENS_PROBE: int = 5      # liveness/health probe
   TEMPERATURE_EXPLORATORY: float = 0.4  # premortem divergence
   ```
3. **Leave as literal with a clarifying comment** only when the value is a
   one-off tuning knob unlikely to be reused (last resort).

**Recommendation:** do NOT silently round token caps that gate output length —
prefer adding `MAX_TOKENS_VERDICT`/`MAX_TOKENS_PROBE` so a verdict gate can never
be accidentally widened. Round only the "roomy" caps (512→500, 800/900→1000).

### B.3 Exact call-site inventory (21 files, 49 sites)

```
weebot/application/flows/states/verifying.py        209,210,250,251,395,396,414,415,436,437,459,460   (12)
weebot/application/services/chain_of_verification.py 195,196,219,220,245,246                            (6)
weebot/application/services/tree_of_thoughts_scorer.py 91,92,125,126                                    (4)
weebot/application/agents/executor/_base.py          455,456,1367                                       (3)  ← incl. new vision reflection
weebot/core/openrouter_enhanced_cascade.py           574,575                                            (2)
weebot/core/model_health.py                          37,38                                              (2)
weebot/application/agents/dreamer.py                 81,82                                              (2)
weebot/application/services/autonomous_learning.py   156,157                                            (2)
weebot/application/services/premortem_analyzer.py    65,66                                              (2)
weebot/application/cqrs/handlers/failure_signature_handlers.py 103,104                                  (2)
weebot/application/flows/harness_opt_flow.py          345,346                                            (2)  ← 345 is computed (0.3 + n*0.1)
weebot/core/agent.py                                 35                                                 (1)  ← uses MODEL_COMMAND_DEFAULT already
weebot/application/agents/retention_agent.py         71                                                 (1)
weebot/core/safety.py                                18                                                 (1)
weebot/application/eval/judges.py                    81                                                 (1)
weebot/tools/mixture_of_agents.py                    203                                                (1)
weebot/tools/bash_security.py                        194                                                (1)
weebot/application/services/main_review_service.py   61                                                 (1)
weebot/application/services/intent_review_service.py 54                                                 (1)
weebot/application/services/step_evaluator.py        102                                                (1)
weebot/qmd_integration/rag_engine.py                 75                                                 (1)
weebot/qmd_integration/query_expander.py             190                                                (1)
weebot/tools/browser_tool.py                         95,120,128                                         (3)  ← temperature=0
```

**Special cases — do NOT mechanically replace:**
- `harness_opt_flow.py:345` — `temperature=0.3 + (len(edits)*0.1)` is a *computed*
  diversity ramp. Replace the base `0.3` with `TEMPERATURE_BALANCED` but keep the
  expression.
- `executor/_base.py:455-456` — our just-added vision-reflection call. `512` →
  `MAX_TOKENS_SHORT` (or new constant); `0.0` → `TEMPERATURE_DETERMINISTIC`.
- `browser_tool.py` / `safety.py` — LangChain `ChatOpenAI(temperature=0)`; same
  substitution applies.

### B.4 Per-file procedure
For each file: add the import (`from weebot.config.constants import TEMPERATURE_*,
MAX_TOKENS_*`), replace literals, run that file's test module. Keep diffs minimal
and behavior-identical (only naming changes, except the deliberate B.2 rounding
which must be called out per-line in the commit body).

---

## 5. Phase C — Message-role literals (LOW, optional)

`"system"`, `"user"`, `"assistant"`, `"tool"`, `"function"` appear as bare
literals across adapters and scorers. Centralize:

```python
# weebot/config/message_roles.py  (new)
ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"
ROLE_FUNCTION = "function"
```

Call sites (non-exhaustive — grep to finalize):
`infrastructure/llm/langchain_adapter.py:32-35`,
`infrastructure/adapters/llm/moonshot_adapter.py:98,118,129`,
`infrastructure/scoring/verifier_scorer.py:63-64`,
`infrastructure/scoring/exact_match_scorer.py:118`.

**Caveat:** these strings are also part of provider wire protocols. Centralizing
is cosmetic, not behavioral — lowest priority, high churn. Recommend deferring
unless doing an adapter refactor anyway. **Decision needed:** include or defer.

---

## 6. Phase D — Test model-string hygiene (LOW)

15 occurrences of `"claude-opus-4-8"` in:
`tests/unit/test_vision_reflection.py`, `tests/unit/test_executor_vision_injection.py`,
`tests/unit/test_llm_multimodal.py`, `scripts/smoke_vision.py`.

Tests pass because `model_supports_vision("claude-opus-4-8")` matches the
`"claude-opus"` substring marker — but the production model is a
Kimi/DeepSeek/Qwen/Grok cascade, so the tests exercise a model family weebot no
longer routes to.

**Options:**
1. Introduce a test-only constant (e.g. `tests/_fixtures/models.py`
   `VISION_TEST_MODEL = MODEL_CASCADE_TIER4`) and reference a real production
   vision model. Requires confirming which cascade model is actually
   vision-capable (Qwen 3.7 Max? verify).
2. Keep `"claude-opus-4-8"` but add a comment that it is a deliberate synthetic
   vision-capable ID for unit isolation.

**Recommendation:** Option 1, parametrize vision tests over the real
vision-capable production model(s) so `model_supports_vision` is tested against
shipped IDs. **Decision needed:** confirm which production cascade models are
vision-capable before rewiring tests.

---

## 7. Suggested execution order

1. **Phase A** (1 file, HIGH) — quick, real correctness/SSOT win.
2. **Phase B** (21 files, MEDIUM) — the bulk; do in 2 commits:
   - B-clean: literals with an exact existing constant (mechanical, zero behavior change).
   - B-new: literals needing new constants (`MAX_TOKENS_VERDICT`, `MAX_TOKENS_PROBE`,
     `TEMPERATURE_EXPLORATORY`) + deliberate roundings, each justified in commit body.
3. **Phase D** (tests, LOW) — after confirming vision-capable production models.
4. **Phase C** (roles, LOW) — defer unless bundled with an adapter refactor.

---

## 8. Guardrails to prevent regression (recommended)

- Add a `ruff`/custom lint or a `pytest` meta-test that greps `weebot/` for
  `temperature=` / `max_tokens=` followed by a numeric literal at any LLM call
  site and fails, allow-listing the genuinely-computed cases
  (`harness_opt_flow.py:345`) and provider-forced ones (`moonshot_adapter.py`).
- Add a meta-test asserting every model string used via `create_llm_adapter(...)`
  in `cli/` and `weebot/` resolves to a constant defined in `model_refs.py`.

---

## 9. Open decisions (resolve before implementing)

1. **Phase A:** route `flow_undo` to `MODEL_COMMAND_DEFAULT` (preferred) or pin a
   new `MODEL_UTILITY_OPENAI = "openai/gpt-4o-mini"` constant?
2. **Phase B.2:** approve adding `MAX_TOKENS_VERDICT(10)`, `MAX_TOKENS_PROBE(5)`,
   `TEMPERATURE_EXPLORATORY(0.4)`; approve rounding 512→500, 800/900→1000,
   200→256, 150→? (no clean target — likely needs its own constant or stays 150).
3. **Phase C:** centralize message roles now or defer?
4. **Phase D:** which production cascade models are vision-capable (for retargeting
   the vision tests)?

---

## 10. Verification per phase

- After each file: run that module's tests (`pytest tests/unit/test_<x>.py`).
- After each phase: full suite `pytest tests/ -q` (baseline must stay green;
  see `memory/test_notes.md` for known pre-existing failures to ignore).
- Phase A: CLI smoke (`python -m cli.main flow ...`).
- No phase is "done" until the full suite matches the pre-change pass count.
