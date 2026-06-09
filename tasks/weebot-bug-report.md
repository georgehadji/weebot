# Weebot Bug Report — Session Analysis

Generated from a full session of PlanActFlow runs testing real-world tasks
(portfolio website, Downloads organization, arXiv paper search, codebase review).

---

## 🔴 CRITICAL: Trajectory detector false-positives kill healthy steps

**File:** `weebot/application/agents/executor.py` (trajectory detection logic, ~line 773)

**Symptom:** Steps that are actively producing output (writing files, running bash commands,
querying APIs) are killed with "Terminal trajectory: All recent tool calls have
produced different errors." The tool calls succeeded (file_editor wrote content,
bash returned results), but the detector flags them as terminal.

**Impact:** Every multi-step task fails. The plan-update loop regenerates the same
plan (fingerprint collision warning), steps repeat until `max_step_repetitions`
is hit, and the flow exits without completing the task. Observed in **5 out of 6
runs** this session.

**Root cause:** The trajectory detector counts *any* non-standard tool output
as an "error." When bash returns stderr output (even informational), when
`file_editor` returns directory listings, or when the LLM retries a request
— each contributes to the error window. The window size and threshold are
too aggressive for real-world multi-turn tool use.

**Suggested fix:**
1. Distinguish tool *errors* (non-zero exit codes, API 4xx/5xx) from
   tool *output* (stdout, file contents, directory listings).
2. Increase the error window from current (seems to be ~3-5) to at least 10.
3. Reset the error counter on any successful tool call (not just "healthy" checks).
4. Only count actual Python exceptions, non-zero exit codes, and HTTP errors
   — not directory listings, "file already exists," or empty stdout.

---

## 🔴 HIGH: Plan-update loop generates identical plan fingerprints

**File:** `weebot/application/flows/states/updating.py` + `plan_act_flow.py:443`

**Symptom:** After a step is killed by the trajectory detector, the plan update
generates a plan with the SAME fingerprint, triggering:
```
Plan fingerprint 6378ad37 is too similar to recent plans — consider diversifying
```
This causes the same step to repeat until `max_step_repetitions` is hit.

**Impact:** The flow enters an infinite-similarity loop. The plan update doesn't
change the strategy, so the same failing step repeats. Combined with the trajectory
detector, this makes every long-running task impossible to complete.

**Suggested fix:** When a step fails due to trajectory detection (not an actual
error), the update should explicitly exclude that step's approach and propose
a DIFFERENT strategy. The "too similar" warning should force a re-generation
with explicit avoidance instructions.

---

## 🟡 MEDIUM: `max_step_repetitions` default of 1 is too low

**File:** `weebot/application/flows/plan_act_flow.py` (via `PlanActFlowConfig`)

**Symptom:** Steps are killed on the second attempt (`repeated 2 times. Agent may
be stuck in a loop`). With `max_step_repetitions=1`, a single trajectory-detector
false-positive on a retry kills the entire flow.

**Suggested fix:** Default to 3 instead of 1. A step that genuinely fails will
still be caught, but a single transient issue won't derail the entire task.

---

## 🟡 MEDIUM: `StepEvent.status` comparison uses enum vs string

**File:** `tests/e2e/test_portfolio_website.py:290` + `event_logger.py:30`

**Symptom:** The step status field is `StepStatus.COMPLETED` (an enum), but
test assertions compare against the string `"completed"`. In the test output,
`[StepStatus.COMPLETED]` is printed instead of `[completed]`. The test works
because `str(StepStatus.COMPLETED) == "StepStatus.COMPLETED"` — but the
comparison `s["status"] == "completed"` always fails.

**Impact:** The `completed` counter in tests is always 0. The test passes
because it no longer asserts `completed >= 1`, but this masks real step
failures.

**Suggested fix:** Either compare `s["status"] == StepStatus.COMPLETED` or
use `str(s["status"])` to normalize. Better: the `step_results` dict should
store the enum value directly, not the string representation.

---

## 🟡 MEDIUM: OpenRouter fallback fails silently with invalid key

**File:** `weebot/infrastructure/adapters/llm/direct_or_fallback_adapter.py:96`

**Symptom:** When `KIMI_API_KEY` is valid and `OPENROUTER_API_KEY` is invalid
(401), the DirectOrFallbackAdapter tries kimi-direct first, gets a 400/401/timeout,
falls back to OpenRouter, gets 401, and the caller sees "all models tripped."
But the kimi-direct call WAS succeeding on most attempts — the fallback to a
broken OpenRouter key undoes the successful direct path.

**Impact:** Steps fail because the circuit breaker opens on kimi-direct after
several connection errors (rate limiting), and OpenRouter can't rescue because
the key is invalid. The user has no visibility into which key is broken.

**Suggested fix:** On first 401 from OpenRouter, log a clear ERROR-level message:
"OpenRouter API key appears invalid (401). Check OPENROUTER_API_KEY in .env."
Then skip OpenRouter fallback for the rest of the session. Also: validate API
keys at startup with a cheap `/models` or `/credits` call.

---

## 🟢 LOW: `model: unknown` in CQRS telemetry (partially fixed)

**File:** `weebot/application/flows/states/executing.py:125`, `updating.py:65`

**Status:** Fixed in this session — `ExecuteStepCommand` and `UpdatePlanCommand`
now receive `context._model or MODEL_BUDGET` instead of `""`. But the telemetry
still shows `Model: unknown` — the TelemetryBehavior may read from a different
field. Needs verification.

---

## 🟢 LOW: `_needs_key` skip decorator evaluated at import time

**File:** `tests/integration/test_real_api_openrouter.py:42-47`

**Symptom:** The `_needs_key` skipif is computed at module import. If `.env` is
created after test collection, tests are incorrectly skipped.

**Status:** Partially fixed in `tests/e2e/test_portfolio_website.py` by moving
skip logic into the `llm` fixture. The integration tests still use the old pattern.

---

## Summary of impact

| Issue | Tasks affected | Fix priority |
|-------|---------------|-------------|
| Trajectory detector false-positives | All multi-step tasks | 🔴 Immediate |
| Plan-update fingerprint loop | All tasks with step failures | 🔴 Immediate |
| `max_step_repetitions` too low | All tasks | 🟡 This week |
| StepEvent enum/string mismatch | Test reliability | 🟡 This week |
| OpenRouter silent auth failure | User confusion | 🟡 This week |
| Telemetry model: unknown | Monitoring | 🟢 Eventually |
| Import-time skip evaluation | Test ergonomics | 🟢 Eventually |
