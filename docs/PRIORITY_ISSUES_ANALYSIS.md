# Priority Issues Analysis — Weebot System (v2)

**Version:** 2.0 — 2026-03-03
**Status:** Previous 3 issues (v1) ALL FIXED. New top 3 identified below.
**Method:** Nash Stability + Minimax Regret + Catastrophic Risk + Adaptation Cost matrix

---

## Context: Previous Issues (v1) — All Fixed

| Issue | Resolution | Status |
|-------|-----------|--------|
| #1 Race condition in AgentContext.shared_data | asyncio.Lock added | ✅ FIXED |
| #2 EventBroker silent event dropping | Exponential backoff retry | ✅ FIXED |
| #3 StateManager blocking async event loop | Consistent ThreadPoolExecutor | ✅ FIXED |

---

## NEW Top 3 Issues (v2)

---

### Issue #1: [CRITICAL] Bare `except:` in ModelRouter Breaks Cancellation

**Classification:** [VERIFIED] — Code confirmed at ai_router.py:197-202
**Location:** `weebot/ai_router.py` lines 197–202 (fallback loop)

**Problem:**
```python
for fallback_id in [m for m in self.MODELS.keys() if m != model_id]:
    try:
        result = await self._call_model(fallback_id, prompt)
        return {"content": result, "source": "fallback", "model": fallback_id}
    except:          # <-- BARE EXCEPT: catches ALL BaseException subclasses
        continue
```

`asyncio.CancelledError` is a subclass of `BaseException` (not `Exception`) in Python 3.8+.
The bare `except:` catches it, swallows it, and continues the loop — preventing proper task cancellation,
graceful shutdown, and timeout enforcement throughout the application.

**Impact:**
- `asyncio.wait_for(generate_with_fallback(...), timeout=X)` — timeout NEVER fires; call hangs
- Ctrl-C or SIGTERM during API call — app cannot shut down cleanly
- `asyncio.Task.cancel()` in orchestration — cancellation silently ignored; orphaned tasks
- Cascading: if one model call hangs, ALL fallbacks are tried before cancellation can propagate

---

### Issue #2: [HIGH] Budget Tracking Exists But Is Never Enforced

**Classification:** [VERIFIED] — `is_budget_exceeded()` defined but never called
**Location:** `weebot/ai_router.py` — `CostTracker.is_budget_exceeded()` + `ModelRouter`

**Problem:**
```python
class CostTracker:
    def is_budget_exceeded(self) -> bool:
        return self.today_cost >= self.daily_budget  # defined...

class ModelRouter:
    async def generate_with_fallback(self, prompt, task_type, use_cache=True):
        # ...
        model_id = self.select_model(task_type)
        result = await self._call_model(model_id, prompt)  # called without budget check!
        # is_budget_exceeded() is NEVER called anywhere
```

The `DAILY_AI_BUDGET` env variable and `daily_budget` parameter are completely inert —
money is tracked in `CostTracker.today_cost` but the gate to stop spending is never raised.

**Impact:**
- Runaway API costs when many agents run in parallel
- No hard stop on budget even when `today_cost >> daily_budget`
- User-configured `DAILY_AI_BUDGET=10` has zero effect
- In orchestration scenarios (Phase 2), dozens of concurrent calls can exhaust budgets in seconds

---

### Issue #3: [MEDIUM] AgentFactory Tool Validation Only Catches Empty Strings

**Classification:** [HYPOTHESIS] — Code at agent_factory.py (tool validation logic)
**Location:** `weebot/core/agent_factory.py` — tool validation in `spawn_agent()`

**Problem:**
```python
# Current validation:
invalid_tools = [t for t in allowed_tools if not t]  # only catches "" or None
if invalid_tools:
    raise ValueError(f"Invalid tool names: {invalid_tools}")

# Missing validation:
# Does NOT check if tool name exists in the registry!
# A typo like "bash_tol" passes validation and spawns an agent that silently has no bash tool.
```

Additionally, when roles are deduplicated:
```python
spawned[role] = agent   # if role "researcher" appears twice, second overwrites first
```

**Impact:**
- Agents spawned with non-existent tool names — tools silently unavailable at runtime
- Tool call fails at execution time (unhelpful `Unknown tool: 'bash_tol'`) not at spawn time
- Duplicate roles in orchestration DAG overwrite silently — lost agents
- Phase 2 WorkflowOrchestrator depends on AgentFactory correctness

---

## Resolution Paths

---

### Issue #1 Paths: Bare `except:` in Fallback Loop

#### Path A: Replace bare `except:` with `except Exception:`
Narrow the catch to `Exception` only, allowing `BaseException` subclasses to propagate.

```python
for fallback_id in [m for m in self.MODELS.keys() if m != model_id]:
    try:
        result = await self._call_model(fallback_id, prompt)
        return {"content": result, "source": "fallback", "model": fallback_id}
    except Exception:
        continue
```

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 1 | Standard Python pattern; minimal surface area change |
| Minimax Regret | 1 | Worst case: some retry-able exceptions no longer retried (low regret) |
| Catastrophic Risk | 1 | Zero data loss risk; cancellation now works correctly |
| Adaptation Cost | 1 | Single character change; zero refactoring |
| **Weighted Score** | **1.00** | |

#### Path B: Explicit exception list with logging
Catch specific expected exceptions and log unexpected ones.

```python
_RETRYABLE = (httpx.HTTPError, aiohttp.ClientError, asyncio.TimeoutError, Exception)
for fallback_id in ...:
    try:
        result = await self._call_model(fallback_id, prompt)
        return {"content": result, "source": "fallback", "model": fallback_id}
    except _RETRYABLE as exc:
        logger.warning("Fallback %s failed: %s", fallback_id, exc)
        continue
```

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 2 | Requires importing httpx/aiohttp — dependency coupling |
| Minimax Regret | 2 | If list incomplete, new provider error types fall through |
| Catastrophic Risk | 1 | Cancellation still propagates |
| Adaptation Cost | 2 | Need to enumerate per-provider exception types |
| **Weighted Score** | **1.75** | |

#### Path C: Wrap entire fallback in asyncio.shield + timeout
Protect individual fallback calls with timeouts, re-raise cancellation.

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 3 | asyncio.shield adds complexity; may delay cancellation |
| Minimax Regret | 3 | If shield misused, worse than bare except |
| Catastrophic Risk | 2 | Shield can mask cancellation in nested calls |
| Adaptation Cost | 3 | Significant logic change |
| **Weighted Score** | **2.75** | |

**SELECTED: Path A** — Score 1.00, trivial change, maximal correctness.

---

### Issue #2 Paths: Budget Not Enforced

#### Path A: Guard at top of `generate_with_fallback()`
Check budget before any API call is attempted.

```python
async def generate_with_fallback(self, prompt, task_type, use_cache=True):
    if self.cost_tracker.is_budget_exceeded():
        raise BudgetExceededError(
            f"Daily budget ${self.daily_budget} exceeded "
            f"(spent: ${self.cost_tracker.today_cost:.4f})"
        )
    # ... rest of method
```

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 1 | Single guard, clear contract, easy to test |
| Minimax Regret | 1 | If check fails, existing behavior (no guard) is maintained |
| Catastrophic Risk | 1 | BudgetExceededError is a domain exception; no data loss |
| Adaptation Cost | 1 | 3 lines added, zero refactoring |
| **Weighted Score** | **1.00** | |

#### Path B: Budget enforcement in `_call_model()`
Check before each individual model call.

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 2 | Checked before each of N fallback attempts (redundant) |
| Minimax Regret | 2 | May allow some calls to start before budget check in parallel |
| Catastrophic Risk | 1 | Same protection as Path A |
| Adaptation Cost | 2 | Must modify private method signature |
| **Weighted Score** | **1.75** | |

#### Path C: Budget as a circuit breaker (integrate with Phase 2 CircuitBreaker)
Register budget limit as a circuit breaker threshold.

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 4 | Requires Phase 2 CircuitBreaker (not yet built) |
| Minimax Regret | 3 | If CircuitBreaker unavailable, no enforcement at all |
| Catastrophic Risk | 2 | Phase 2 dependency introduces timeline risk |
| Adaptation Cost | 4 | Major architectural dependency |
| **Weighted Score** | **3.25** | |

**SELECTED: Path A** — Score 1.00, immediate fix with zero dependencies.

---

### Issue #3 Paths: AgentFactory Tool Validation Gap

#### Path A: Validate tool names against ToolCollection at spawn time
Lookup tool names in the actual registry before creating the agent.

```python
def _validate_tools(self, allowed_tools: list[str], registry) -> None:
    available = {t.name for t in registry}
    missing = [t for t in allowed_tools if t and t not in available]
    if missing:
        raise ValueError(f"Unknown tools requested: {missing}")
```

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 1 | Fail-fast at spawn, clear error message |
| Minimax Regret | 2 | If registry not passed to spawn, validation may be skipped |
| Catastrophic Risk | 1 | ValidationError at spawn is recoverable |
| Adaptation Cost | 2 | Requires passing registry reference to spawn_agent |
| **Weighted Score** | **1.50** | |

#### Path B: Raise ValueError on duplicate roles in spawn_orchestrator_agents
Guard against silent dict key overwrite.

```python
def spawn_orchestrator_agents(self, role_configs):
    spawned = {}
    for role, config in role_configs.items():
        if role in spawned:
            raise ValueError(f"Duplicate role '{role}' in orchestrator config")
        spawned[role] = await self.spawn_agent(role, config)
    return spawned
```

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 1 | Guards a clear contract violation |
| Minimax Regret | 1 | Existing behavior (overwrite) was already wrong |
| Catastrophic Risk | 1 | Raises at spawn time, not at runtime |
| Adaptation Cost | 1 | 3-line guard |
| **Weighted Score** | **1.00** | |

#### Path C: Both A and B (combined)
Apply tool name validation AND duplicate role detection together.

| Metric | Score | Rationale |
|--------|-------|-----------|
| Nash Stability | 1 | Two independent orthogonal fixes |
| Minimax Regret | 1 | Both cases caught |
| Catastrophic Risk | 1 | Both issues eliminated |
| Adaptation Cost | 2 | Slightly more code than either alone |
| **Weighted Score** | **1.25** | |

**SELECTED: Path C** — Score 1.25, closes both related gaps in one pass.

---

## Selected Optimal Paths Summary

| Issue | Selected Path | Score | Key Benefit |
|-------|--------------|-------|-------------|
| #1 Bare except | A — `except Exception:` | 1.00 | One character change, full fix |
| #2 Budget not enforced | A — Guard at top of generate_with_fallback | 1.00 | 3 lines, immediate enforcement |
| #3 Tool validation | C — Validate names + guard duplicate roles | 1.25 | Two fixes in one pass |

**Overall Strategy:** Surgical minimal changes — zero new dependencies, zero new files needed.

---

*Version 2.0 — 2026-03-03*
*Previous v1 issues resolved. These 3 new issues require immediate implementation.*
