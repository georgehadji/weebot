# Remediation Plan — 8 Critical Issues from Live Run

> Based on the `site02` session log. Every problem is traced to exact line numbers.

---

## 🔴 Critical

### Problem 1: All 4 cascade models tripped → agent loops forever

**Evidence from the run:**
```
Circuit breaker tripped for minimax/minimax-m3
Circuit breaker tripped for x-ai/grok-build-0.1
Circuit breaker tripped for qwen/qwen3.7-max
Circuit breaker tripped for deepseek/deepseek-v4-pro
```
Followed by: Trajectory exhaustion at 90%, 92%, 94%, 96% — the agent burned through the entire 50-step budget making guaranteed-to-fail calls.

**Root cause:** `_call_with_cascade()` [executor.py:350-410] has an "ultimate fallback" at line 400 that tries TIER4 "even if tripped." But when ALL models are tripped (including TIER4 from a prior call), the ultimate fallback also fails. The method returns `None` or raises, and the step loop continues with `self._step_budget.consume()` never detecting that no model is available.

Additionally, when the ultimate fallback fails, the exception propagates as a generic tool error, which the policy-error-loop detection [executor.py:432-450] counts toward consecutive error thresholds — but never recognizes "all models are dead" as a terminal condition.

**Fix (4 locations):**

#### Fix 1a: Return a sentinel error when no model is available

In `_call_with_cascade()`, before the ultimate fallback:

```python
# executor.py, after line 399 (Phase 2 exhausted), BEFORE ultimate fallback
# ── All models tripped — signal terminal condition ──
from weebot.core.error_classifier import ErrorClassifier, ErrorCategory

class AllModelsTrippedError(Exception):
    """Raised when every model in the cascade has been circuit-broken."""
    pass

# ... inside _call_with_cascade, replace lines 395-410:
        # ── Phase 2: sequential fallback through remaining tiers ──
        remaining = [m for m in (self._TIER3_MODEL, self._TIER4_MODEL)
                     if not _is_tripped(m)]
        for model_id in remaining:
            resp = await _try_chat(model_id)
            if resp is not None:
                await self._track_usage_and_maybe_compress(resp)
                return resp

        # ── All models tripped — raise terminal error ──
        raise AllModelsTrippedError(
            f"All {len(self._circuit_breaker_failures)} models in the cascade "
            f"have tripped their circuit breakers. Check OpenRouter credits at "
            f"https://openrouter.ai/credits"
        )
```

#### Fix 1b: Catch AllModelsTrippedError in execute_step

In `execute_step()`, the main `while self._step_budget.consume():` loop [executor.py:420-510]:

```python
# Inside the while loop, after _call_with_cascade:
    try:
        response = await self._call_with_cascade(messages, description=step.description)
    except AllModelsTrippedError as exc:
        yield ErrorEvent(error=str(exc))
        yield MessageEvent(
            role="assistant",
            message=(
                "All AI models are currently unavailable. Please:\n"
                "1. Check your OpenRouter credits at https://openrouter.ai/credits\n"
                "2. Verify your OPENROUTER_API_KEY is valid\n"
                "3. Wait a few minutes for circuit breakers to cool down and retry"
            ),
        )
        break  # Exit the step loop immediately
```

#### Fix 1c: Increase Phase 1 timeout to reduce false tripping

```python
# executor.py, line 349 — change timeout from 2.0 to 5.0 for first attempt
async def _try_chat(model_id: str, timeout: float = 5.0) -> LLMResponse | None:
```

Keep it at 2.0s for Phase 2 retries (sequential fallback).

#### Fix 1d: Reset circuit breakers on new session

In `execute_step()` [executor.py:415], clear circuit breaker state at step start:

```python
# At the beginning of execute_step():
self._circuit_breaker_failures.clear()
```

NOTE: Only clear if the previous step completed successfully. If the previous step also failed, keep the breakers tripped (they're protecting the API).

---

### Problem 2: Planner JSON parsing produces "Extra data" errors

**Evidence:**
```
JSONDecodeError: Extra data: line 1 column 17 (char 16)
```
Response was: `{"title": "Plan"}\n\nExtra explanatory text here...`

**Root cause:** `_extract_json_object()` [planner.py:140-144] uses `content.rfind("}")` to find the last `}`. But `rfind` finds the LAST closing brace in the entire string. If the response is:
```
{"title": "Plan"}  ← this is the JSON
Some extra explanation about the plan...
```
The extraction produces `{"title": "Plan"}\n\nSome extra explanation...` which is NOT valid JSON because of the trailing text. However, if the response has a nested JSON or code block after the plan:
```
{"title": "Plan", "steps": [{"id": "1", "description": "do X"}]}
```  
Then `rfind("}")` correctly finds the last brace of the nested structure. The problem is when there's text AFTER the JSON object but no additional braces.

**Fix:** Use `json.JSONDecoder.raw_decode()` which parses exactly one JSON object and returns the index where it stopped:

```python
# planner.py — replace _extract_json_object and _parse_json_content:

import json as _json_mod

@classmethod
def _parse_json_content(cls, content: str) -> Dict[str, Any]:
    cleaned = cls._strip_code_fences(content)

    # Try strict parse first (fast path)
    try:
        return _json_mod.loads(cleaned)
    except _json_mod.JSONDecodeError:
        pass

    # Try raw_decode — stops at first complete JSON object
    try:
        decoder = _json_mod.JSONDecoder()
        obj, _ = decoder.raw_decode(cleaned)
        if isinstance(obj, dict):
            return obj
    except _json_mod.JSONDecodeError:
        pass

    # Try extracting between first { and matching }
    start = cleaned.find("{")
    if start != -1:
        # Find matching closing brace (handle nesting)
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return _json_mod.loads(cleaned[start:i + 1])
                    except _json_mod.JSONDecodeError:
                        break

    # Last resort: try old rfind approach
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return _json_mod.loads(cleaned[start:end + 1])
        except _json_mod.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract valid JSON from: {cleaned[:200]}")
```

This handles:
1. Clean JSON → fast path
2. JSON with trailing text → `raw_decode` stops at first complete object
3. JSON with nested braces → brace-counting finds the matching `}`
4. Everything else → old rfind as last resort

---

## 🟡 High

### Problem 3: 2-second Phase 1 timeout causes false tripping

**Evidence:** All 4 models tripped in a single step. Under normal conditions, at least one model should respond. The 2-second timeout in Phase 1 is too aggressive — models under load or with cold starts can take 3-5 seconds for the first token.

**Root cause:** `_try_chat()` [executor.py:348] wraps `self._llm.chat()` in `asyncio.wait_for(..., timeout=2.0)`. If 3 models are fired in parallel and all take >2s, all 3 get marked as failures, and after 3 attempts the circuit breaker trips.

**Fix:**

```python
# executor.py — modify _call_with_cascade to use tiered timeouts

async def _try_chat(self, model_id: str, timeout: float = 5.0) -> LLMResponse | None:
    """Try a chat call with configurable timeout."""
    if _is_tripped(model_id):
        return None
    try:
        resp = await asyncio.wait_for(
            self._llm.chat(
                messages=messages,
                tools=self._tools.to_params(),
                tool_choice="auto",
                model=model_id,
                temperature=TEMPERATURE,
            ),
            timeout=timeout,
        )
        if resp and (resp.content or resp.tool_calls):
            return resp
        _record_failure(model_id)
        return None
    except (asyncio.TimeoutError, Exception) as exc:
        if isinstance(exc, Exception) and ErrorClassifier.should_fail_fast(exc):
            raise
        logger.debug("Model %s failed (%.1fs timeout): %s", model_id, timeout, exc)
        _record_failure(model_id)
        return None

# In _call_with_cascade, Phase 1 uses 5s, Phase 2 uses 3s:
# Phase 1: fire task-model + tier1 in parallel with 5s timeout
tasks = {asyncio.ensure_future(_try_chat(m, timeout=5.0)): m for m in parallel_models}

# Phase 2: sequential with 3s timeout
for model_id in remaining:
    resp = await _try_chat(model_id, timeout=3.0)
```

---

### Problem 4: Complex command chains blocked without audit trail

**Evidence:**
```
Suspicious command detected: Complex command chain (6 operators)
```

**Root cause:** `BashGuard` [bash_guard.py] blocks commands with 6+ operators. The full command is not logged, making debugging impossible. The agent can't know WHY it was blocked or what alternative to try.

**Fix:** Add the full command to the safety check output:

```python
# bash_guard.py — modify format_check_results() to include the command

def evaluate(self, command: str) -> tuple[RiskLevel, list[SafetyCheck]]:
    # ... existing logic ...
    return max_risk, checks

# In bash_tool.py, where evaluate() is called:
risk, checks = guard.evaluate(command)
if risk == RiskLevel.SUSPICIOUS:
    logger.info(
        "Suspicious command: %s (operators: %d, risk: %s)",
        command[:200],
        command.count("|") + command.count(";") + command.count("&"),
        risk.value,
    )
```

And in the executor, when a tool call is blocked, include the reason in the `ToolResult`:

```python
# executor.py — in _execute_tool_call:
if result.is_error and "blocked" in (result.error or "").lower():
    result = ToolResult.error_result(
        f"{result.error}\n\nTip: Try splitting complex commands into simpler, "
        f"single-operation calls. Use file_editor to write multi-step scripts "
        f"instead of chaining commands with | ; &"
    )
```

---

## 🟠 Medium

### Problem 5: TrajectoryMonitor recovery messages never reach a tripped LLM

**Evidence:** Trajectory exhaustion at 90-96% with recovery messages being generated, but the LLM can't receive them because it's tripped.

**Root cause:** `TrajectoryMonitor.diagnose()` [trajectory_monitor.py:120-135] produces a `recovery_message` that gets injected into the conversation buffer. But when all models are tripped, the LLM never gets a chance to read it.

**Fix:** TrajectoryMonitor should detect "all attempts failing" as a terminal condition:

```python
# trajectory_monitor.py — add to diagnose():

# 5. All attempts failing — terminal condition
if used_budget > 5 and _all_recent_attempts_failed(used_budget):
    return TrajectoryDiagnosis(
        health=TrajectoryHealth.TERMINAL,
        detail="All recent tool calls have failed — models may be unavailable",
        recovery_message=None,  # No recovery — stop the step
        affected_step_ids=[step_id],
    )
```

Add `TrajectoryHealth.TERMINAL` to the enum in `trajectory.py`:

```python
class TrajectoryHealth(str, Enum):
    HEALTHY = "healthy"
    REPEATING = "repeating"
    SEMANTIC_LOOP = "semantic_loop"
    STAGNATING = "stagnating"
    EXHAUSTED = "exhausted"
    TERMINAL = "terminal"  # NEW — stop immediately
```

In `ExecutingState`, handle `TERMINAL` by transitioning to `UpdatingState`:

```python
# executing.py — in the trajectory diagnosis handler:
if diagnosis.health == TrajectoryHealth.TERMINAL:
    yield ErrorEvent(error=f"Terminal trajectory: {diagnosis.detail}")
    context.set_state(UpdatingState())
    return
```

---

### Problem 6: Planner uses `model or "default"` which is not a valid model

**Evidence:**
```
CreatePlanCommand(session_id=..., prompt=..., model=context._model or "default", ...)
```

**Root cause:** `PlanningState.execute()` [planning.py:73] passes `"default"` as a fallback model name. This string is not a valid OpenRouter model ID and will fail if `context._model` is None.

**Fix:**

```python
# planning.py:73 — replace "default" with MODEL_BUDGET
from weebot.config.model_refs import MODEL_BUDGET

cmd_result = await context._mediator.send(
    CreatePlanCommand(
        session_id=context._session.id,
        prompt=prompt,
        model=context._model or MODEL_BUDGET,
        context=context._session.context.model_dump(mode="json"),
    )
)
```

---

## 🔵 Low

### Problem 7: No .pyc cache clearing in startup sequence

**Evidence:** User must manually run `find . -type d -name __pycache__ -exec rm -rf {} +` before every session.

**Fix:** Add to `run.py` startup:

```python
# run.py — after imports, before any weebot imports:
import shutil
from pathlib import Path

def _clear_stale_bytecode():
    """Remove __pycache__ directories that may contain stale .pyc files."""
    root = Path(__file__).parent
    count = 0
    for pycache in root.rglob("__pycache__"):
        try:
            shutil.rmtree(pycache)
            count += 1
        except OSError:
            pass
    if count:
        print(f"  Cleared {count} stale bytecode cache(s)")

# Call before any weebot imports:
_clear_stale_bytecode()
```

---

### Problem 8: `_call_with_cascade` doesn't surface API error details

**Evidence:** All models tripped with no indication of WHY (rate limit? no credits? auth error?).

**Fix:** Log the actual error from the first failure:

```python
# In _try_chat, capture and log the first error per model:
_first_error: dict[str, str] = {}

async def _try_chat(model_id: str, timeout: float = 5.0) -> LLMResponse | None:
    ...
    except (asyncio.TimeoutError, Exception) as exc:
        if model_id not in _first_error:
            _first_error[model_id] = str(exc)[:200]
            logger.warning(
                "Model %s first error: %s",
                model_id,
                _first_error[model_id],
            )
```

---

## Implementation Order

| # | Problem | Files | Effort | Risk |
|---|---------|-------|--------|------|
| 1 | All models tripped → agent loops | `executor.py` | 30 min | Low (adds new error type) |
| 2 | JSON parser Extra data | `planner.py` | 20 min | Low (more robust, no behavior change) |
| 3 | 2s Phase 1 timeout | `executor.py` | 15 min | Low (just change numbers) |
| 4 | Command chain audit trail | `bash_guard.py`, `bash_tool.py` | 15 min | Low (adds logging) |
| 5 | Terminal trajectory detection | `trajectory_monitor.py`, `trajectory.py` | 20 min | Med (new enum value) |
| 6 | "default" model fallback | `planning.py` | 5 min | Low (one line) |
| 7 | .pyc cache clearing | `run.py` | 10 min | Low (startup only) |
| 8 | API error logging | `executor.py` | 10 min | Low (adds logging) |

**Total: ~2 hours.** All changes are isolated to single files with low cross-cutting risk.

---

## Architectural Compliance Audit

Every fix is verified against weebot's Clean Architecture (Hexagonal) principles:

```
Interfaces → Infrastructure → Application → Domain
                 ↑                ↑
            (depends on)     (depends on)
```

### Layer Map

| Fix | File(s) | Layer | Direction Check |
|-----|---------|-------|-----------------|
| 1a | `executor.py` | **Application** (agents) | ✅ Imports from `core/error_classifier.py` (Cross-cutting → allowed) |
| 1b | `executor.py` | **Application** (agents) | ✅ Yields `ErrorEvent` + `MessageEvent` from `domain/models/event.py` (inward) |
| 1c | `executor.py` | **Application** (agents) | ✅ Pure numeric change, no new imports |
| 1d | `executor.py` | **Application** (agents) | ✅ Accesses `self._circuit_breaker_failures` (same class), no external deps |
| 2 | `planner.py` | **Application** (agents) | ✅ Uses `json.JSONDecoder` (stdlib). No domain/infrastructure imports |
| 3 | `executor.py` | **Application** (agents) | ✅ Pure numeric change, no new imports |
| 4 | `bash_guard.py` | **Core** (cross-cutting) | ✅ Core has zero outward deps. `logger.info()` uses stdlib `logging` |
| 4 | `bash_tool.py` | **Tools** (infrastructure-ish) | ✅ Tools → Core is allowed. Returns `ToolResult` from `tools/base.py` (same layer) |
| 5 | `trajectory_monitor.py` | **Application** (services) | ✅ Consumes `TrajectoryDiagnosis` from `domain/models/trajectory.py` (inward) |
| 5 | `trajectory.py` | **Domain** (models) | ✅ New enum value — zero imports. Domain remains pure |
| 5 | `executing.py` | **Application** (flows/states) | ✅ Yields `ErrorEvent` from domain, calls `context.set_state()` (same layer) |
| 6 | `planning.py` | **Application** (flows/states) | ✅ Imports from `config/model_refs.py` (Config layer, allowed via Application → Config) |
| 7 | `run.py` | **Entry point** (outside Clean Architecture) | ✅ Entry points can import anything. Uses `shutil` + `pathlib` (stdlib) |
| 8 | `executor.py` | **Application** (agents) | ✅ Adds `logger.warning()` — stdlib logging. No new architecture deps |

### Principles Preserved

| Principle | Status |
|-----------|--------|
| **Domain purity** — zero imports from outer layers | ✅ No fix touches domain except Fix 5 (adds enum value to existing domain model — no new imports) |
| **Dependency inversion** — Application depends on Domain, not vice versa | ✅ All application-layer fixes import from domain (models/events) or stdlib, never from infrastructure |
| **CQRS Mediator** — commands through pipeline behaviors | ✅ No fix changes Mediator. Fix 6 uses existing `CreatePlanCommand` — no command schema changes |
| **Immutable models** — Pydantic v2 with `model_copy()` | ✅ No fix creates mutable state. `AllModelsTrippedError` is a plain Exception, not a model |
| **Port/Adapter separation** — abstract ports in application, concrete adapters in infrastructure | ✅ No fix creates new ports or adapters. All changes are to existing concrete classes |
| **FlowState pattern** — state transitions via `context.set_state()` | ✅ Fix 5 uses existing `context.set_state(UpdatingState())` — no new states added |

### One Architectural Judgment Call

**`AllModelsTrippedError` placement:** Should this live in `weebot/domain/exceptions.py` (Domain layer) or in `executor.py` (Application layer)?

Decision: **Keep it in `executor.py`.** Rationale:
- It's not a domain concept — it's an infrastructure failure specific to the model cascade
- Domain exceptions (`BudgetExceededError`, `SafetyError`) represent business rules, not operational failures
- The error is caught and handled entirely within the same file
- If other components need it later, extract to `weebot/application/agents/errors.py` (still Application layer, not Domain)

### No Circular Dependencies Introduced

```
Before:  planner.py → domain/models/plan.py (✅ inward)
After:   planner.py → domain/models/plan.py (✅ inward, unchanged)

Before:  executor.py → domain/models/event.py (✅ inward)
After:   executor.py → domain/models/event.py (✅ inward, unchanged)

Before:  trajectory_monitor.py → domain/models/trajectory.py (✅ inward)
After:   trajectory_monitor.py → domain/models/trajectory.py (✅ inward, unchanged)
```

**Verdict: All 8 fixes respect the architecture. Zero layer violations. Zero new circular dependencies.**
