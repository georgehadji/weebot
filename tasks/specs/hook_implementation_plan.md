# Hook System Implementation Plan

**Status:** Draft — ready to implement  
**Architecture layer:** Application (ports) + Infrastructure (templates) + crosscut (flows/agents)  
**Dependency direction:** All changes point inward; no new outward dependencies introduced.

---

## Context

The `HookRegistry` / `HookRegistryPort` system was connected to `PlanActFlow` in the previous session.
Five lifecycle stages are wired: `pre_execute`, `post_execute`, `pre_task`, `post_task`, `on_error`.
The items below extend coverage, improve context richness, add new stages, and harden the system.

---

## Phase 1 — Foundation (do first; later phases depend on these)

### 1.1 TypedDict context contracts

**Why:** Hook functions receive `**context` as a plain dict. Type annotations make it impossible to accidentally omit a key or pass the wrong type.

**File:** `weebot/application/ports/hook_context_types.py` (new file)

```python
"""TypedDict schemas for HookRegistry context dicts.

Each stage has its own TypedDict so callsites are statically checkable
and hook authors know exactly what keys are guaranteed.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, TypedDict


class PreExecuteContext(TypedDict):
    session_id: str
    prompt: str
    plan: Optional[Any]          # None on first call


class PostExecuteContext(TypedDict):
    session_id: str
    plan: Optional[Any]
    status: str                  # "completed" | "max_iterations" | "stuck"
    elapsed_ms: float
    total_tokens: int            # executor token total (0 if unavailable)


class PreTaskContext(TypedDict):
    session_id: str
    step_id: str
    step_description: str
    step_index: int              # 0-based position in plan.steps
    total_steps: int
    plan: Any


class PostTaskContext(TypedDict):
    session_id: str
    step_id: str
    step_description: str
    elapsed_ms: float
    plan: Any


class OnErrorContext(TypedDict):
    session_id: str
    step_id: str
    error: str
    error_type: str              # "step_failure" | "plan_stuck" | "bash_guard" | "executor"
    plan: Optional[Any]


class PreToolCallContext(TypedDict):
    session_id: str
    step_id: str
    tool_name: str
    tool_args: Dict[str, Any]


class PostToolCallContext(TypedDict):
    session_id: str
    step_id: str
    tool_name: str
    tool_args: Dict[str, Any]
    result: Any
    elapsed_ms: float
    success: bool


class PostPlanCreatedContext(TypedDict):
    session_id: str
    plan: Any
    step_count: int
    elapsed_ms: float


class PostPlanUpdatedContext(TypedDict):
    session_id: str
    plan: Any
    step_count: int
    elapsed_ms: float
    reason: str


class PostBashGuardContext(TypedDict):
    session_id: str
    command: str
    risk_level: str              # "SAFE" | "SUSPICIOUS" | "DANGEROUS" | "BLOCKED"
    allowed: bool


class PostVerificationContext(TypedDict):
    session_id: str
    scores: Dict[str, int]       # {correctness, completeness, specificity, restraint}
    gate_failures: List[str]
    inconsistency_count: int


class PostCompleteContext(TypedDict):
    session_id: str
    plan: Optional[Any]
    tool_count: int
    error_count: int
    total_elapsed_ms: float
    plan_fingerprint: str
```

**Architecture note:** This file lives in `application/ports/` (pure Python typing, no I/O, no framework imports). It is the single source of truth for context shapes. Import it in both callsites and hook implementations.

---

### 1.2 `frozenset` VALID_STAGES + `get_valid_stages()` on port

**Why:** `VALID_STAGES` is a mutable `set` today; a stale reference could be modified by test code. Expose it on the port so external registries can validate without importing the concrete class.

**File:** `weebot/templates/hooks.py`

```python
# Change:
VALID_STAGES = {PRE_EXECUTE, POST_EXECUTE, PRE_TASK, POST_TASK, ON_ERROR}
# To:
VALID_STAGES: frozenset[str] = frozenset({PRE_EXECUTE, POST_EXECUTE, PRE_TASK, POST_TASK, ON_ERROR})
```

**File:** `weebot/application/ports/hook_registry_port.py`

```python
@runtime_checkable
class HookRegistryPort(Protocol):
    async def execute_hooks(
        self, stage: str, context: Dict[str, Any]
    ) -> Dict[str, Any]: ...

    def get_valid_stages(self) -> frozenset[str]: ...
```

**File:** `weebot/templates/hooks.py` — add to `HookRegistry`:

```python
def get_valid_stages(self) -> frozenset[str]:
    return self.VALID_STAGES
```

---

## Phase 2 — New Callsites on Existing Stages

### 2.1 Enrich sparse context dicts

All context dicts should match their corresponding TypedDict. These are surgical edits to existing `execute_hooks` call sites.

#### 2.1.1 `pre_execute` context (plan_act_flow.py ~line 200)

Add `"plan": None` → already present. Add nothing extra yet (plan doesn't exist at pre_execute).

#### 2.1.2 `post_execute` context (plan_act_flow.py — after while loop)

**Current:**
```python
await self._hooks.execute_hooks("post_execute", {
    "session_id": self._session.id,
    "plan": self._plan,
    "status": "completed",
})
```

**Target:**
```python
_post_elapsed_ms = (_time.monotonic() - self._flow_started_at) * 1000
_total_tokens = 0
if self._executor and hasattr(self._executor, "token_usage"):
    _total_tokens = self._executor.token_usage.get("total_tokens", 0)
await self._hooks.execute_hooks("post_execute", {
    "session_id": self._session.id,
    "plan": self._plan,
    "status": "completed",
    "elapsed_ms": _post_elapsed_ms,
    "total_tokens": _total_tokens,
})
```

#### 2.1.3 `on_error` contexts

Every `on_error` call needs `"error_type"`. Three callsites:

- **plan_act_flow.py** (PlanStuckError): add `"error_type": "plan_stuck"`
- **executing.py** (execution_failed): add `"error_type": "step_failure"`
- (Phase 3.4) bash_guard: add `"error_type": "bash_guard"`

#### 2.1.4 `pre_task` context (executing.py ~line 103)

**Current:**
```python
await context._hooks.execute_hooks("pre_task", {
    "session_id": context._session.id,
    "step_id": step.id,
    "step_description": step.description,
    "plan": context._plan,
})
```

**Target:**
```python
_step_index = next(
    (i for i, s in enumerate(context._plan.steps) if s.id == step.id), 0
)
await context._hooks.execute_hooks("pre_task", {
    "session_id": context._session.id,
    "step_id": step.id,
    "step_description": step.description,
    "step_index": _step_index,
    "total_steps": len(context._plan.steps),
    "plan": context._plan,
})
```

---

### 2.2 `post_plan_created` stage (planning.py)

**New stage name:** `"post_plan_created"`

**Register in `HookRegistry`:**
```python
POST_PLAN_CREATED = "post_plan_created"
VALID_STAGES = frozenset({..., POST_PLAN_CREATED})
```

**Insertion point:** `planning.py` line 91-93 — after `context._plan = Plan.model_validate(event.plan)` on the `PlanStatus.CREATED` branch.

```python
if isinstance(event, PlanEvent) and event.status == PlanStatus.CREATED:
    context._plan = Plan.model_validate(event.plan)
    logger.info("Plan created with %d steps in %.1fs", ...)
    # ── Hook: post_plan_created ──────────────────────────────────────
    if getattr(context, "_hooks", None) is not None:
        await context._hooks.execute_hooks("post_plan_created", {
            "session_id": context._session.id,
            "plan": context._plan,
            "step_count": len(context._plan.steps),
            "elapsed_ms": _plan_elapsed * 1000,
        })
```

---

### 2.3 `post_plan_updated` stage (updating.py)

**New stage name:** `"post_plan_updated"`

**Register in `HookRegistry`:**
```python
POST_PLAN_UPDATED = "post_plan_updated"
VALID_STAGES = frozenset({..., POST_PLAN_UPDATED})
```

**Insertion point:** `updating.py` line 84-86 — after `context._plan = Plan.model_validate(event.plan)` on `PlanStatus.UPDATED` branch (mediator path).

```python
if isinstance(event, PlanEvent) and event.status == PlanStatus.UPDATED:
    context._plan = Plan.model_validate(event.plan)
    update_success = True
    # ── Hook: post_plan_updated ──────────────────────────────────────
    if getattr(context, "_hooks", None) is not None:
        await context._hooks.execute_hooks("post_plan_updated", {
            "session_id": context._session.id,
            "plan": context._plan,
            "step_count": len(context._plan.steps),
            "elapsed_ms": _update_elapsed * 1000,
            "reason": f"Step {last_step.id} {last_step.status.value}",
        })
```

---

## Phase 3 — New Stages

### 3.1 `post_verification` stage (verifying.py)

**New stage name:** `"post_verification"`

**Register in `HookRegistry`:**
```python
POST_VERIFICATION = "post_verification"
```

**Insertion point:** `verifying.py` line 174-178 — after `ctx.extra["gate_failures"] = gate_failures` is set, before `flow.set_state(CompletedState())`.

```python
# Store scores + gate results on session for stamp
if hasattr(flow._session, "context"):
    ctx = flow._session.context
    try:
        ctx.extra["verification_scores"] = scores
        ctx.extra["gate_failures"] = gate_failures
    except Exception:
        pass

# ── Hook: post_verification ──────────────────────────────────────────
if getattr(flow, "_hooks", None) is not None:
    await flow._hooks.execute_hooks("post_verification", {
        "session_id": flow._session.id,
        "scores": scores,
        "gate_failures": gate_failures,
        "inconsistency_count": len(inconsistencies),
    })

# ── Transition to Completed ────────────────────────────────────────
from weebot.application.flows.states.completed import CompletedState
flow.set_state(CompletedState())
```

**Note:** `inconsistencies` is built in `execute()` and is in scope at this point (line 109 declares it).

---

### 3.2 `post_complete` stage (completed.py)

**New stage name:** `"post_complete"`

**Register in `HookRegistry`:**
```python
POST_COMPLETE = "post_complete"
```

**Insertion point:** `completed.py` after line 112 — after `_total_elapsed` is computed, before the function returns.

```python
import time as _time
_total_elapsed = _time.monotonic() - context._flow_started_at
logger.info("PlanActFlow completed for session %s in %.1fs", ...)

# ── Hook: post_complete ──────────────────────────────────────────────
if getattr(context, "_hooks", None) is not None:
    _fingerprint = ""
    if context._plan:
        from weebot.application.services.plan_history import PlanHistory
        _fingerprint = PlanHistory.plan_fingerprint(context._plan)
    await context._hooks.execute_hooks("post_complete", {
        "session_id": context._session.id,
        "plan": context._plan,
        "tool_count": sum(
            1 for e in context._session.events
            if type(e).__name__ == "ToolEvent"
        ),
        "error_count": sum(
            1 for e in context._session.events
            if type(e).__name__ == "ErrorEvent"
        ),
        "total_elapsed_ms": _total_elapsed * 1000,
        "plan_fingerprint": _fingerprint,
    })
```

**Note:** `tool_count`/`error_count` are already computed in the SessionStamp block above this point (lines 79-80). Extract them into local vars earlier to avoid duplicate iteration.

---

### 3.3 `pre_tool_call` / `post_tool_call` stages (executor)

**New stage names:** `"pre_tool_call"`, `"post_tool_call"`

These fire inside `ExecutorAgent` (or `StructuredExecutorAgent`) around each tool dispatch. The executor does not receive a `HookRegistry` today — it needs to be wired through `PlanActFlowConfig` or via a new `ExecutorConfig` field.

**Preferred wiring:** Add `hooks: Optional[Any] = None` to `ExecutorAgent.__init__` and pass `cfg.hooks` when constructing the executor in `PlanActFlow.__init__`.

**File:** `weebot/application/agents/executor.py` — find the section that dispatches a tool call (look for `await tool.run(...)` or similar). Wrap:

```python
# Pre-tool hook
if self._hooks is not None:
    await self._hooks.execute_hooks("pre_tool_call", {
        "session_id": session_id,
        "step_id": step_id,
        "tool_name": tool.name,
        "tool_args": tool_args,
    })

_tool_t0 = _time.monotonic()
result = await tool.run(**tool_args)
_tool_elapsed = (_time.monotonic() - _tool_t0) * 1000

# Post-tool hook
if self._hooks is not None:
    await self._hooks.execute_hooks("post_tool_call", {
        "session_id": session_id,
        "step_id": step_id,
        "tool_name": tool.name,
        "tool_args": tool_args,
        "result": result,
        "elapsed_ms": _tool_elapsed,
        "success": not isinstance(result, Exception),
    })
```

**Architecture note:** The executor lives in `application/agents/`. Accepting a `HookRegistryPort` here is valid — it is an Application layer abstraction receiving an Application port. No layer boundary is violated.

---

### 3.4 `post_bash_guard` stage (bash_guard.py)

**New stage name:** `"post_bash_guard"`

**Why:** The bash guard is the security boundary. Operators need to observe every BLOCKED or DANGEROUS decision in real time (alerting, audit logs).

**Problem:** `bash_guard.py` lives in `weebot/core/`, which is the cross-cutting layer. It currently has no session context and no hook registry. Rather than plumbing the registry down to core, expose the hook call through a module-level optional registry reference set at startup:

**File:** `weebot/core/bash_guard.py` — add at top:

```python
# Optional global hook registry set once at container bootstrap.
# Using a module-level singleton avoids threading hooks through every call site.
_bash_guard_hooks: Optional[Any] = None

def set_bash_guard_hooks(registry: Any) -> None:
    """Wire a HookRegistryPort instance for post_bash_guard events."""
    global _bash_guard_hooks
    _bash_guard_hooks = registry
```

Inside `check_command(command, session_id="")`:

```python
result = _classify(command)  # existing logic

if _bash_guard_hooks is not None:
    import asyncio
    try:
        coro = _bash_guard_hooks.execute_hooks("post_bash_guard", {
            "session_id": session_id,
            "command": command,
            "risk_level": result.risk_level.value,
            "allowed": result.allowed,
        })
        # Synchronous guard — schedule hook as a fire-and-forget task
        # if there is a running event loop; otherwise skip.
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            pass  # no event loop — hooks not available
    except Exception:
        pass  # bash guard must never fail due to a hook

return result
```

**Registration at startup:** In `container.py` or wherever `BashGuard` is initialised, call `set_bash_guard_hooks(hook_registry_instance)`.

**Architecture note:** Module-level singleton is acceptable here because `bash_guard.py` is already stateless and shared globally. It mirrors how Python's `logging` module works.

---

## Phase 4 — Advanced Features

### 4.1 `pre_task` cancellation mechanism

**Why:** A hook observer (e.g. a cost-control hook) may want to abort execution before a step starts.

**Protocol:** If any hook registered on `pre_task` raises `StepCancelledError`, `ExecutingState` catches it and transitions directly to `VerifyingState` (graceful stop, not an error).

**File:** `weebot/application/ports/hook_registry_port.py` — add sentinel exception:

```python
class StepCancelledError(Exception):
    """Raised by a pre_task hook to cancel the current step gracefully."""
    def __init__(self, reason: str = ""):
        super().__init__(reason)
        self.reason = reason
```

**File:** `weebot/templates/hooks.py` — modify `execute_hooks` to propagate `StepCancelledError`:

```python
except StepCancelledError:
    raise  # propagate — caller decides whether to honour
except Exception as e:
    _log.error(f"Hook '{hook.name}' failed at stage '{stage}': {e}")
```

**File:** `executing.py` — wrap the `pre_task` call:

```python
from weebot.application.ports.hook_registry_port import StepCancelledError
try:
    if getattr(context, "_hooks", None) is not None:
        await context._hooks.execute_hooks("pre_task", {...})
except StepCancelledError as e:
    logger.info("Step %s cancelled by hook: %s", step.id, e.reason)
    context._plan = context._plan.update_step_status(step.id, StepStatus.COMPLETED,
                                                      result=f"Cancelled: {e.reason}")
    context.set_state(VerifyingState())
    return
```

---

### 4.2 New `HookConditions`

**File:** `weebot/templates/hooks.py` — add to `HookConditions` class:

```python
@staticmethod
def tool_name_is(*names: str):
    """Condition that matches when tool_name is one of the given names."""
    def condition(context: Dict) -> bool:
        return context.get("tool_name", "") in names
    return condition

@staticmethod
def risk_level_at_least(level: str):
    """Fires when bash_guard risk_level >= the given level."""
    _order = {"SAFE": 0, "SUSPICIOUS": 1, "DANGEROUS": 2, "BLOCKED": 3}
    threshold = _order.get(level.upper(), 0)
    def condition(context: Dict) -> bool:
        actual = _order.get(context.get("risk_level", "SAFE").upper(), 0)
        return actual >= threshold
    return condition

@staticmethod
def step_elapsed_exceeds(ms: int):
    """Fires when a step took longer than `ms` milliseconds."""
    def condition(context: Dict) -> bool:
        return context.get("elapsed_ms", 0) > ms
    return condition

@staticmethod
def token_total_exceeds(n: int):
    """Fires when post_execute total_tokens > n."""
    def condition(context: Dict) -> bool:
        return context.get("total_tokens", 0) > n
    return condition

@staticmethod
def gate_failed(gate_name: str):
    """Fires when post_verification gate_failures contains gate_name."""
    def condition(context: Dict) -> bool:
        return gate_name in context.get("gate_failures", [])
    return condition
```

---

### 4.3 `BuiltinPlanActHooks` class

**Why:** Ship useful default observers so teams can drop in real functionality without writing boilerplate.

**File:** `weebot/templates/hooks.py` — add after `BuiltinHooks`:

```python
class BuiltinPlanActHooks:
    """Ready-made hook functions for PlanActFlow lifecycle stages.

    Usage::

        registry = HookRegistry()
        BuiltinPlanActHooks.register_all(registry)
    """

    @staticmethod
    def log_plan_created(session_id: str, step_count: int, elapsed_ms: float, **_):
        _log.info("[Hook] Plan created: %d steps in %.0fms (session=%s)",
                  step_count, elapsed_ms, session_id)

    @staticmethod
    def log_step_start(session_id: str, step_id: str, step_description: str,
                       step_index: int, total_steps: int, **_):
        _log.info("[Hook] Step %d/%d starting: %s (session=%s)",
                  step_index + 1, total_steps, step_description[:80], session_id)

    @staticmethod
    def log_step_done(session_id: str, step_id: str, elapsed_ms: float, **_):
        _log.info("[Hook] Step %s done in %.0fms (session=%s)",
                  step_id, elapsed_ms, session_id)

    @staticmethod
    def log_verification(session_id: str, scores: dict, gate_failures: list, **_):
        _log.info("[Hook] Verification: scores=%s gates_failed=%s (session=%s)",
                  scores, gate_failures, session_id)

    @staticmethod
    def log_complete(session_id: str, tool_count: int, error_count: int,
                     total_elapsed_ms: float, **_):
        _log.info("[Hook] Flow complete: %d tools, %d errors, %.0fms (session=%s)",
                  tool_count, error_count, total_elapsed_ms, session_id)

    @staticmethod
    def alert_on_blocked_command(session_id: str, command: str,
                                  risk_level: str, allowed: bool, **_):
        if not allowed:
            _log.warning("[SECURITY] Blocked command '%s...' (session=%s)",
                         command[:60], session_id)

    @staticmethod
    def register_all(registry: "HookRegistry") -> None:
        registry.register("post_plan_created", BuiltinPlanActHooks.log_plan_created,
                          priority=0, name="log_plan_created")
        registry.register("pre_task", BuiltinPlanActHooks.log_step_start,
                          priority=0, name="log_step_start")
        registry.register("post_task", BuiltinPlanActHooks.log_step_done,
                          priority=0, name="log_step_done")
        registry.register("post_verification", BuiltinPlanActHooks.log_verification,
                          priority=0, name="log_verification")
        registry.register("post_complete", BuiltinPlanActHooks.log_complete,
                          priority=0, name="log_complete")
        registry.register("post_bash_guard", BuiltinPlanActHooks.alert_on_blocked_command,
                          priority=100, name="alert_blocked_command",
                          condition=HookConditions.risk_level_at_least("BLOCKED"))
```

---

## Phase 5 — `post_llm_call` (optional, deferred)

**Why:** Allows token metering, latency tracking, and model-level observability per LLM invocation.

**Complexity:** The LLM call path goes through the model cascade in `weebot/infrastructure/adapters/`. The `cascade.py` file wraps several adapters. Wiring a hook here requires passing the registry into the Infrastructure layer — a dependency direction violation unless the port is defined in Domain/Application and injected.

**Recommended approach:** Define `PostLlmCallContext` TypedDict now (in `hook_context_types.py`). Defer the actual wiring until the Infrastructure layer receives a proper `LlmObserverPort` that `HookRegistryPort` can satisfy via structural subtyping — same pattern as the bash guard.

**Status:** Out of scope for this sprint.

---

## Implementation Order

```
Phase 1.1  →  hook_context_types.py (new)
Phase 1.2  →  VALID_STAGES frozenset + get_valid_stages()
Phase 2.1  →  Enrich existing context dicts (4 callsites)
Phase 2.2  →  post_plan_created callsite (planning.py)
Phase 2.3  →  post_plan_updated callsite (updating.py)
Phase 3.1  →  post_verification stage (verifying.py)
Phase 3.2  →  post_complete stage (completed.py)
Phase 3.3  →  pre_tool_call / post_tool_call (executor.py)
Phase 3.4  →  post_bash_guard (bash_guard.py)
Phase 4.1  →  StepCancelledError + pre_task cancellation
Phase 4.2  →  New HookConditions (5 methods)
Phase 4.3  →  BuiltinPlanActHooks class
```

Each item in Phases 1-3 is independent after Phase 1.1 is done.
Phases 4.1-4.3 depend only on the stage being registered in VALID_STAGES.

---

## Files Touched (summary)

| File | Change type |
|------|-------------|
| `weebot/application/ports/hook_context_types.py` | NEW |
| `weebot/application/ports/hook_registry_port.py` | MODIFIED — add `get_valid_stages()`, `StepCancelledError` |
| `weebot/templates/hooks.py` | MODIFIED — frozenset, new stages, `BuiltinPlanActHooks`, `HookConditions`, `get_valid_stages()` |
| `weebot/application/flows/plan_act_flow.py` | MODIFIED — enrich `post_execute`/`on_error` context dicts |
| `weebot/application/flows/states/planning.py` | MODIFIED — add `post_plan_created` hook call |
| `weebot/application/flows/states/executing.py` | MODIFIED — enrich `pre_task` context, add `StepCancelledError` handling |
| `weebot/application/flows/states/updating.py` | MODIFIED — add `post_plan_updated` hook call |
| `weebot/application/flows/states/verifying.py` | MODIFIED — add `post_verification` hook call |
| `weebot/application/flows/states/completed.py` | MODIFIED — add `post_complete` hook call |
| `weebot/application/agents/executor.py` | MODIFIED — accept hooks, add `pre_tool_call`/`post_tool_call` |
| `weebot/core/bash_guard.py` | MODIFIED — add `set_bash_guard_hooks()` + fire-and-forget hook |

---

## Test Requirements

Each new stage needs at minimum:

1. A unit test asserting the hook fires with the correct keys in the context dict.
2. A test asserting that a hook that raises a non-`StepCancelledError` exception does NOT crash the host.
3. For `pre_task` cancellation: a test asserting the step is marked `COMPLETED` and the state transitions to `VerifyingState`.

Test file location: `tests/unit/test_hooks.py` and `tests/unit/test_hook_context_types.py`.

---

## Architecture Compliance Notes

- **Dependency rule preserved:** `hook_context_types.py` is in `application/ports/` (inward from flows/agents). `HookRegistryPort` stays in `application/ports/`. `HookRegistry` stays in `templates/` (Infrastructure-equivalent layer). No new outward dependency is introduced.
- **Bash guard pattern:** Module-level singleton is consistent with how Python's `logging` module and `BashGuard._singleton` are used elsewhere in `core/`. It avoids passing the registry through every function signature.
- **SOLID compliance:** Open-Closed — new stages extend `VALID_STAGES` without touching existing hook logic. Liskov — `HookRegistry` satisfies `HookRegistryPort` structurally. Dependency Inversion — flows depend on the Port, not the concrete class.
- **No new imports across layer boundaries:** The `executing.py` import `from weebot.application.ports.hook_registry_port import StepCancelledError` is Application→Application (valid). The `plan_act_flow.py` hooks access remains `Optional[Any]` with structural duck-typing.
