# Multi-Agent Enhancements — Implementation Plan

**Source spec:** [`multiagent_patterns_integration_plan.md`](multiagent_patterns_integration_plan.md)
**Architecture:** Hexagonal (Clean Architecture). Dependency rule: `Interfaces → Infrastructure → Application → Domain`
**Implementation sequence:** #4 → #6 → #1 → #7 → #2 → #3 → #5+8 (ROI-first, dependency-ordered)
**Total scope:** ~760 lines across 22 files (13 new, 9 edits). Zero new Python dependencies.

---

## Table of Contents

1. [Step 1 — Pre-call Compaction (3 lines)](#step-1--pre-call-compaction-improvement-4)
2. [Step 2 — StepProgressEvaluation (~160 lines)](#step-2--stepprogress-evaluation-improvement-6)
3. [Step 3 — Middleware Chain (~80 lines)](#step-3--middleware-chain-improvement-1)
4. [Step 4 — ToolApprovalRequest UX (~47 lines)](#step-4--toolapprovalrequest-ux-improvement-7)
5. [Step 5 — Composable Termination (~165 lines)](#step-5--composable-termination-improvement-2)
6. [Step 6 — EvalRunner (~240 lines)](#step-6--evalrunner-improvement-3)
7. [Step 7 — RAG Memory with Port (~65 lines)](#step-7--rag-memory-with-port-improvements-5--8)
8. [Cross-Cutting Concerns](#cross-cutting-concerns)
9. [Validation Protocol](#validation-protocol)

---

## Step 1 — Pre-call Compaction (Improvement #4)

**Priority:** P0 | **Effort:** 3 lines | **Risk:** None | **Dependencies:** None

### Problem

`_maybe_compress()` at `_base.py:308` fires via `_track_usage_and_maybe_compress(resp)` AFTER each LLM response (lines 474, 484, 496). The compacted buffer only benefits the *next* LLM call. If the current call hits the context window ceiling, it gets a truncated response or an API error before compaction ever runs.

### Change

**File:** `weebot/application/agents/executor/_base.py`

Insert a pre-call compaction at the top of the step loop, before message assembly at line 721:

```python
# Line 719: self._step_budget.reset()
# Line 720: while self._step_budget.consume():
# >>> INSERT HERE (new line 721):
            await self._maybe_compress()
# Line 721 (becomes 722): messages = [{"role": "system", ...
```

The existing `_maybe_compress()` already guards on `self._auto_compress` and the 75% threshold. The post-call calls on lines 474/484/496 remain — they update token counters. This addition ensures compaction fires *before* the LLM sees the messages.

### Test Plan

No new test file needed. Verify via existing tests:
```bash
pytest tests/unit/tools/test_executor_agent.py -v -k "compress"
```

Add one assertion in the existing executor tests confirming that `_maybe_compress` is called before `_call_with_cascade` (mock ordering).

### Rollback

Revert the single inserted line. Post-call compaction continues to work as before.

---

## Step 2 — StepProgressEvaluation (Improvement #6)

**Priority:** P0 | **Effort:** ~160 lines | **Risk:** Medium | **Dependencies:** None

### Problem

After each step, `ExecutingState` runs `StepResultValidator` (rule-based: empty, short, error-string, repetition checks at `executing.py:309-338`), then marks the step COMPLETED. There is no evaluation of whether the step actually advanced the plan toward its goal. The "silently wrong" failure mode — agent completes all steps but the aggregate result is incorrect — goes undetected.

### Architecture

New `StepEvaluatorPort` in the application ports layer. `ExecutingState` calls it after `StepResultValidator` passes. If the evaluator reports regression, the flow transitions to `UpdatingState` with `force_replan=True`. The evaluator is a port, not a concrete implementation, enabling:
- **NoOpStepEvaluator** — always passes (backward-compatible default)
- **LLMStepEvaluator** — calls a cheap model to score step output against plan goals

### Files

#### 1. `weebot/application/ports/step_evaluator_port.py` (NEW — ~30 lines)

```python
"""Port for evaluating step progress against plan goals."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from weebot.domain.models.plan import Plan, Step


@dataclass(frozen=True)
class StepEvaluation:
    step_id: str
    score: float  # 0.0–1.0
    passed: bool
    regression_detected: bool
    reasoning: str
    recommendations: list[str] = field(default_factory=list)


class StepEvaluatorPort(ABC):
    @abstractmethod
    async def evaluate(
        self,
        step: Step,
        output: str,
        plan: Plan,
        previous_outputs: list[str],
    ) -> StepEvaluation: ...
```

#### 2. `weebot/application/services/step_evaluator.py` (NEW — ~80 lines)

```python
"""LLM-based step progress evaluator."""
from __future__ import annotations

import json
import logging
from typing import Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.step_evaluator_port import StepEvaluation, StepEvaluatorPort
from weebot.domain.models.plan import Plan, Step

logger = logging.getLogger(__name__)

_EVAL_PROMPT = """\
You are evaluating whether an agent's step output advances the plan toward its goal.

Plan goal: {plan_goal}
Current step: {step_description}
Step output:
{output}

Previous step outputs (most recent first):
{previous_outputs}

Score the step output from 0.0 to 1.0:
- 1.0: Step fully completed, clear progress toward goal
- 0.7+: Substantial progress, minor gaps
- 0.4-0.7: Partial progress, significant gaps
- 0.0-0.4: No meaningful progress or regression

Respond with JSON:
{{"score": float, "regression_detected": bool, "reasoning": "one sentence", "recommendations": ["if any"]}}
"""


class NoOpStepEvaluator(StepEvaluatorPort):
    async def evaluate(
        self, step: Step, output: str, plan: Plan, previous_outputs: list[str],
    ) -> StepEvaluation:
        return StepEvaluation(
            step_id=step.id, score=1.0, passed=True,
            regression_detected=False, reasoning="no-op evaluator",
        )


class LLMStepEvaluator(StepEvaluatorPort):
    def __init__(
        self,
        llm: LLMPort,
        model: Optional[str] = None,
        threshold: float = 0.4,
    ) -> None:
        self._llm = llm
        self._model = model
        self._threshold = threshold

    async def evaluate(
        self, step: Step, output: str, plan: Plan, previous_outputs: list[str],
    ) -> StepEvaluation:
        prev_summary = "\n".join(
            f"  [{i+1}] {o[:200]}" for i, o in enumerate(previous_outputs[-3:])
        ) or "  (none)"

        prompt = _EVAL_PROMPT.format(
            plan_goal=plan.title or plan.message or "",
            step_description=step.description,
            output=output[:2000],
            previous_outputs=prev_summary,
        )
        try:
            resp = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._model,
                temperature=0.0,
            )
            data = json.loads(resp.content or "{}")
            score = float(data.get("score", 1.0))
            regression = bool(data.get("regression_detected", False))
            return StepEvaluation(
                step_id=step.id,
                score=score,
                passed=score >= self._threshold and not regression,
                regression_detected=regression,
                reasoning=data.get("reasoning", ""),
                recommendations=data.get("recommendations", []),
            )
        except Exception as exc:
            logger.warning("StepEvaluator LLM call failed: %s — passing step", exc)
            return StepEvaluation(
                step_id=step.id, score=1.0, passed=True,
                regression_detected=False, reasoning=f"eval failed: {exc}",
            )
```

#### 3. `weebot/application/flows/states/executing.py` — EDIT (~15 lines)

Insert after the existing `StepResultValidator` block (after line 338), before the step completion block at line 340:

```python
        # ── Improvement 6: Step progress evaluation (LLM-based) ────────
        _step_evaluator = getattr(context, "_step_evaluator", None)
        if _step_evaluator is not None and step.result:
            _prev_outputs = [
                s.result for s in context._plan.steps
                if s.is_done() and s.id != step.id and s.result
            ]
            _eval = await _step_evaluator.evaluate(
                step=step,
                output=str(step.result),
                plan=context._plan,
                previous_outputs=_prev_outputs,
            )
            if not _eval.passed:
                logger.warning(
                    "Step '%s' failed progress eval (score=%.2f, regression=%s): %s",
                    step.id, _eval.score, _eval.regression_detected, _eval.reasoning,
                )
                context.set_state(UpdatingState())
                return
```

#### 4. `weebot/application/models/plan_act_flow_config.py` — EDIT (~3 lines)

Add field after `code_reviewer` (line 64):

```python
    step_evaluator: Optional[Any] = None  # StepEvaluatorPort — per-step progress evaluation
```

#### 5. `weebot/application/flows/plan_act_flow.py` — EDIT (~2 lines)

In `__init__`, after `self._code_reviewer = cfg.code_reviewer` (line 148):

```python
        self._step_evaluator = cfg.step_evaluator
```

### Test Plan

**New file:** `tests/unit/services/test_step_evaluator.py` (~50 lines)

```python
import pytest
from weebot.application.ports.step_evaluator_port import StepEvaluation
from weebot.application.services.step_evaluator import NoOpStepEvaluator, LLMStepEvaluator
from weebot.domain.models.plan import Plan, Step


@pytest.mark.asyncio
async def test_noop_evaluator_always_passes():
    evaluator = NoOpStepEvaluator()
    step = Step(id="s1", description="test")
    plan = Plan(title="test plan", steps=[step])
    result = await evaluator.evaluate(step, "output", plan, [])
    assert result.passed is True
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_llm_evaluator_regression_detection(mock_llm):
    # mock_llm returns {"score": 0.2, "regression_detected": true, ...}
    evaluator = LLMStepEvaluator(llm=mock_llm, threshold=0.4)
    step = Step(id="s1", description="implement feature")
    plan = Plan(title="build app", steps=[step])
    result = await evaluator.evaluate(step, "deleted everything", plan, ["created feature"])
    assert result.passed is False
    assert result.regression_detected is True


@pytest.mark.asyncio
async def test_llm_evaluator_passes_on_failure(mock_llm_error):
    # mock_llm raises Exception
    evaluator = LLMStepEvaluator(llm=mock_llm_error, threshold=0.4)
    step = Step(id="s1", description="test")
    plan = Plan(title="test", steps=[step])
    result = await evaluator.evaluate(step, "output", plan, [])
    assert result.passed is True  # fail-open
```

### Risk Mitigation

- **Infinite replan loop:** Mitigated by existing `PlanHistory` (3 consecutive similar plans triggers `PlanStuckError`).
- **LLM failure:** Fail-open — returns `passed=True` so flow continues.
- **Cost:** Use cheapest available model via `model` param. Evaluator prompt is ~300 tokens.

---

## Step 3 — Middleware Chain (Improvement #1)

**Priority:** P0 | **Effort:** ~80 lines | **Risk:** Low | **Dependencies:** Step 1 (compaction must be pre-call before middleware wraps the call)

### Problem

`Middleware` ABC at `middleware/base.py` defines `before_request`, `after_response`, `after_tool_call`. `SubAgentMiddleware` at `middleware/subagent.py` implements it. But zero references exist in `weebot/application/agents/` — the ABC is designed but never connected to the executor's LLM call path.

### Files

#### 1. `weebot/application/middleware/chain.py` (NEW — ~50 lines)

```python
"""MiddlewareChain — ordered pipeline of Middleware instances."""
from __future__ import annotations

import logging
from typing import Any

from weebot.application.middleware.base import (
    Middleware,
    MiddlewareRequest,
    MiddlewareResponse,
    ToolCallResult,
)

logger = logging.getLogger(__name__)


class MiddlewareChain:
    def __init__(self, middlewares: list[Middleware] | None = None) -> None:
        self._middlewares: list[Middleware] = list(middlewares or [])

    def is_empty(self) -> bool:
        return len(self._middlewares) == 0

    def add(self, middleware: Middleware) -> None:
        self._middlewares.append(middleware)

    async def apply_before_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        step_id: str = "",
        step_description: str = "",
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        request = MiddlewareRequest(
            messages=messages, tools=tools,
            step_id=step_id, step_description=step_description,
        )
        state: dict[str, Any] = {}
        for mw in self._middlewares:
            request, state = await mw.before_request(request, state)
        return request.messages, request.tools

    async def apply_after_response(
        self,
        content: str,
        tool_calls: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        response = MiddlewareResponse(content=content, tool_calls=tool_calls)
        request = MiddlewareRequest(messages=messages, tools=tools)
        state: dict[str, Any] = {}
        for mw in self._middlewares:
            response, state = await mw.after_response(response, request, state)
        return response.content, response.tool_calls

    async def apply_after_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        output: str,
        error: str | None,
        is_error: bool,
    ) -> ToolCallResult:
        result = ToolCallResult(
            tool_name=tool_name, arguments=arguments,
            output=output, error=error, is_error=is_error,
        )
        state: dict[str, Any] = {}
        for mw in self._middlewares:
            result, state = await mw.after_tool_call(result, state)
        return result
```

#### 2. `weebot/application/agents/executor/_base.py` — EDIT (~30 lines total, 4 insertion points)

**(A) Import + `__init__` param** — after line 155 (`harness_instruction_block` param):

```python
        middleware_chain: Optional["MiddlewareChain"] = None,
```

Store as `self._middleware_chain = middleware_chain` after line 169.

**(B) Pre-request middleware** — in the step loop, after pre-call compaction (new line 721 from Step 1) and before `messages = [...]` assembly at line 722:

```python
            if self._middleware_chain is not None and not self._middleware_chain.is_empty():
                _mw_msgs = [{"role": "system", "content": self._system_prompt}] + list(self._conversation_buffer)
                _mw_msgs, _mw_tools = await self._middleware_chain.apply_before_request(
                    messages=_mw_msgs,
                    tools=self._tools.to_params() if self._tools else [],
                    step_id=step.id,
                    step_description=step.description,
                )
```

Then use `_mw_msgs` as the messages for `_call_with_cascade` when middleware ran, otherwise fall through to the original `messages` assembly.

**(C) Post-response middleware** — after `response = await self._call_with_cascade(messages, ...)` returns (line 724), before appending to buffer:

```python
            if self._middleware_chain is not None and not self._middleware_chain.is_empty():
                assistant_content, _modified_tool_calls = await self._middleware_chain.apply_after_response(
                    content=response.content or "",
                    tool_calls=response.tool_calls or [],
                    messages=messages,
                    tools=self._tools.to_params() if self._tools else [],
                )
                if response.tool_calls and _modified_tool_calls:
                    response = response  # tool_calls are passed by reference in the list
```

**(D) Post-tool middleware** — in the tool results loop (after line 831 `for tc, result in zip(...)`), after each tool result is processed:

```python
                if self._middleware_chain is not None and not self._middleware_chain.is_empty():
                    _mw_result = await self._middleware_chain.apply_after_tool_call(
                        tool_name=tool_name,
                        arguments=event_args,
                        output=result.output or "",
                        error=result.error,
                        is_error=result.is_error,
                    )
                    if _mw_result.output != (result.output or ""):
                        result = result._replace(output=_mw_result.output) if hasattr(result, '_replace') else result
```

#### 3. `weebot/application/flows/plan_act_flow.py` — EDIT (~3 lines)

In the `executor_kwargs` dict (line 215), add:

```python
            middleware_chain=cfg.middleware_chain,
```

#### 4. `weebot/application/models/plan_act_flow_config.py` — EDIT (~2 lines)

Add field after `hooks` (line 104):

```python
    middleware_chain: Optional[Any] = None  # MiddlewareChain — interceptor pipeline for LLM calls
```

### Test Plan

**New file:** `tests/unit/middleware/test_middleware_chain.py` (~60 lines)

- `test_empty_chain_passthrough` — messages/tools unchanged
- `test_single_middleware_modifies_tools` — SubAgentMiddleware adds `task` tool
- `test_ordered_execution` — 2 middlewares, verify call order
- `test_after_tool_call_intercepts` — middleware modifies tool output

### Risk

Low. Empty chain is the default (backward-compatible). Per-LLM-call overhead < 1ms for sync middleware.

---

## Step 4 — ToolApprovalRequest UX (Improvement #7)

**Priority:** P1 | **Effort:** ~47 lines | **Risk:** Low | **Dependencies:** None

### Problem

When BashGuard + `ExecApprovalPolicy` classifies a command as DANGEROUS and returns `requires_confirmation=True`, the tool execution returns an error string like "requires user confirmation". The LLM sees this error and may retry or give up. There is no structured pause/resume event — the UX is an error message, not a deliberate approval flow.

### Architecture

Add `ToolApprovalEvent` to the domain event model. When the executor detects `requires_confirmation=True`, it emits `ToolApprovalEvent` instead of the error string. The `ExecutingState` event loop handles it like `WaitForUserEvent` — pauses the flow and yields control to the CLI/UI.

### Files

#### 1. `weebot/domain/models/event.py` — EDIT (~15 lines)

After `PlanReviewEvent` (line 84), add:

```python
class ToolApprovalEvent(BaseEvent):
    """Emitted when a tool call requires user approval before execution."""
    type: Literal["tool_approval"] = "tool_approval"
    tool_name: str = Field(default="")
    arguments: Dict[str, Any] = Field(default_factory=dict)
    risk_level: str = Field(default="")
    reason: str = Field(default="")
    prompt: str = Field(default="Allow this command? (yes/no)")
```

Add `ToolApprovalEvent` to the `AgentEvent` Union at line 195.

Update the import in `executing.py` (line 10):

```python
from weebot.domain.models.event import AgentEvent, ErrorEvent, MessageEvent, ToolEvent, ToolApprovalEvent, WaitForUserEvent
```

#### 2. `weebot/application/agents/executor/_base.py` — EDIT (~15 lines)

In the tool execution path, when `requires_confirmation` is True, emit `ToolApprovalEvent` instead of returning an error `ToolResult`. The exact location is in `_execute_tool_batch()` or the tool dispatch logic where BashGuard's result is checked. Add:

```python
                # If tool requires confirmation, emit approval event instead of error
                if hasattr(result, 'requires_confirmation') and result.requires_confirmation:
                    yield ToolApprovalEvent(
                        tool_name=tool_name,
                        arguments=event_args,
                        risk_level=getattr(result, 'risk_level', 'DANGEROUS'),
                        reason=getattr(result, 'reason', 'Requires user confirmation'),
                    )
                    return  # Pause execution — flow will resume on user approval
```

#### 3. `weebot/application/flows/states/executing.py` — EDIT (~12 lines)

In the event consumption loop (line 236), add handling for `ToolApprovalEvent`:

```python
            if isinstance(event, ToolApprovalEvent):
                hitl_paused = True
                logger.info(
                    "Tool '%s' requires approval (risk=%s): %s",
                    event.tool_name, event.risk_level, event.reason,
                )
```

The existing `hitl_paused` handling at line 262 already pauses the flow and sets session status to WAITING.

### Test Plan

- Extend existing BashGuard tests to verify `ToolApprovalEvent` is emitted for DANGEROUS commands
- Verify existing `WaitForUserEvent` resume path works for `ToolApprovalEvent`

### Risk

Low. `ToolApprovalEvent` is additive. The existing error-return path stays as fallback for any consumer that doesn't handle the new event type.

---

## Step 5 — Composable Termination (Improvement #2)

**Priority:** P1 | **Effort:** ~165 lines | **Risk:** Low | **Dependencies:** None

### Problem

`MAX_EXECUTOR_STEPS=50` hardcoded at `constants.py`. `max_iterations` in PlanActFlow's `run()` loop at line 477. `TokenBudgetMonitor` is observability-only — no `should_terminate()`. No token-budget termination, no wall-clock timeout, no text-mention trigger, and no composition of multiple conditions.

### Architecture

New `termination/` package at the application layer. Each strategy implements a common ABC. `CompositeTermination` supports AND/OR via `__or__`/`__and__` operators. PlanActFlow checks termination at the top of each loop iteration.

### Files

#### 1. `weebot/application/termination/__init__.py` (NEW — ~5 lines)

```python
"""Composable termination conditions for agent flows."""
from weebot.application.termination.base import TerminationCondition, TerminationResult
from weebot.application.termination.conditions import (
    CompositeTermination,
    MaxIterationTermination,
    TokenBudgetTermination,
    TextMentionTermination,
    WallClockTermination,
)
```

#### 2. `weebot/application/termination/base.py` (NEW — ~40 lines)

```python
"""Base classes for termination conditions."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TerminationContext:
    iteration: int = 0
    total_tokens: int = 0
    elapsed_seconds: float = 0.0
    last_messages: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class TerminationResult:
    should_terminate: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.should_terminate


class TerminationCondition(ABC):
    @abstractmethod
    def check(self, ctx: TerminationContext) -> TerminationResult: ...

    def __or__(self, other: TerminationCondition) -> CompositeTermination:
        from weebot.application.termination.conditions import CompositeTermination
        return CompositeTermination([self, other], mode="any")

    def __and__(self, other: TerminationCondition) -> CompositeTermination:
        from weebot.application.termination.conditions import CompositeTermination
        return CompositeTermination([self, other], mode="all")
```

#### 3. `weebot/application/termination/conditions.py` (NEW — ~100 lines)

```python
"""Concrete termination conditions."""
from __future__ import annotations

from weebot.application.termination.base import (
    TerminationCondition,
    TerminationContext,
    TerminationResult,
)


class MaxIterationTermination(TerminationCondition):
    def __init__(self, max_iterations: int) -> None:
        self._max = max_iterations

    def check(self, ctx: TerminationContext) -> TerminationResult:
        if ctx.iteration >= self._max:
            return TerminationResult(True, f"max iterations ({self._max}) reached")
        return TerminationResult(False)


class TokenBudgetTermination(TerminationCondition):
    def __init__(self, max_tokens: int) -> None:
        self._max = max_tokens

    def check(self, ctx: TerminationContext) -> TerminationResult:
        if ctx.total_tokens >= self._max:
            return TerminationResult(True, f"token budget ({self._max}) exhausted")
        return TerminationResult(False)


class WallClockTermination(TerminationCondition):
    def __init__(self, max_seconds: float) -> None:
        self._max = max_seconds

    def check(self, ctx: TerminationContext) -> TerminationResult:
        if ctx.elapsed_seconds >= self._max:
            return TerminationResult(
                True,
                f"wall clock timeout ({self._max:.0f}s) exceeded",
            )
        return TerminationResult(False)


class TextMentionTermination(TerminationCondition):
    def __init__(self, text: str, scan_last_n: int = 5) -> None:
        self._text = text.lower()
        self._scan_last_n = scan_last_n

    def check(self, ctx: TerminationContext) -> TerminationResult:
        if ctx.last_messages:
            for msg in ctx.last_messages[-self._scan_last_n:]:
                content = str(msg.get("content", "")).lower()
                if self._text in content:
                    return TerminationResult(
                        True, f"text '{self._text}' mentioned in output",
                    )
        return TerminationResult(False)


class CompositeTermination(TerminationCondition):
    def __init__(
        self,
        conditions: list[TerminationCondition],
        mode: str = "any",
    ) -> None:
        self._conditions = list(conditions)
        self._mode = mode  # "any" = OR, "all" = AND

    def check(self, ctx: TerminationContext) -> TerminationResult:
        results = [c.check(ctx) for c in self._conditions]
        if self._mode == "any":
            for r in results:
                if r.should_terminate:
                    return r
            return TerminationResult(False)
        else:  # "all"
            reasons = [r.reason for r in results if r.should_terminate]
            if len(reasons) == len(self._conditions):
                return TerminationResult(True, "; ".join(reasons))
            return TerminationResult(False)
```

#### 4. `weebot/application/services/token_budget_monitor.py` — EDIT (~5 lines)

Add method after `should_compact()` (line 171):

```python
    def should_terminate(self, breakdown: TokenBreakdown, threshold: float = 0.95) -> bool:
        if breakdown.max_capacity == 0:
            return False
        return breakdown.total_used / breakdown.max_capacity >= threshold
```

#### 5. `weebot/application/models/plan_act_flow_config.py` — EDIT (~2 lines)

Add field after `auto_terminate_on_plan_complete` (line 59):

```python
    termination_conditions: Optional[list] = None  # list[TerminationCondition]
```

#### 6. `weebot/application/flows/plan_act_flow.py` — EDIT (~15 lines)

In `__init__`, after `self._max_iterations = cfg.max_iterations` (line 172):

```python
        self._termination_conditions = cfg.termination_conditions or []
```

In `run()`, at the top of the while loop (line 484), after `iteration_count += 1`:

```python
            # ── Composable termination check ──────────────────────────
            if self._termination_conditions:
                import time as _term_time
                _term_ctx = TerminationContext(
                    iteration=iteration_count,
                    total_tokens=self._executor.token_usage.get("total_tokens", 0),
                    elapsed_seconds=_term_time.monotonic() - self._flow_started_at,
                )
                for _tc in self._termination_conditions:
                    _result = _tc.check(_term_ctx)
                    if _result.should_terminate:
                        self._log.info("Termination condition met: %s", _result.reason)
                        self.set_state(CompletedState(termination_reason=_result.reason))
                        return
```

#### 7. `weebot/application/flows/states/completed.py` — EDIT (~5 lines)

Add `termination_reason` to `CompletedState.__init__`:

```python
    def __init__(self, termination_reason: str = "") -> None:
        self._termination_reason = termination_reason
```

Log it in `execute()`.

### Test Plan

**New file:** `tests/unit/termination/test_termination.py` (~90 lines)

- `test_max_iteration_terminates` — triggers at N
- `test_token_budget_terminates` — triggers at threshold
- `test_wall_clock_terminates` — triggers after elapsed
- `test_text_mention_terminates` — detects keyword in messages
- `test_composite_or` — any condition triggers
- `test_composite_and` — all conditions required
- `test_operator_composition` — `cond1 | cond2` and `cond1 & cond2`

---

## Step 6 — EvalRunner (Improvement #3)

**Priority:** P1 | **Effort:** ~240 lines | **Risk:** Medium | **Dependencies:** None

### Problem

`StagedEvaluator` at `staged_evaluator.py` is a cost-saving probe layer — the caller provides `eval_fn`. There is no built-in judge, no per-criterion scoring, and no metrics pipeline. Evaluation quality depends entirely on what the caller passes.

### Architecture

Build on top of `StagedEvaluator` — keep its probe-then-full cost optimization. Add:
- `JudgePort` (application port) — abstract judge interface
- `CriterionScore` / `JudgeVerdict` — per-criterion scoring (name, score 0-10, reasoning)
- `ModelJudge` — LLM-based judge implementation
- `ScoreJudge` — rule-based scoring (fast, no LLM cost)
- `EvalRunner` — orchestrates evaluation tasks with aggregation

### Files

#### 1. `weebot/application/ports/judge_port.py` (NEW — ~35 lines)

```python
"""Port for evaluation judges."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CriterionScore:
    name: str
    score: float  # 0.0–10.0
    reasoning: str = ""


@dataclass(frozen=True)
class JudgeVerdict:
    criteria: list[CriterionScore] = field(default_factory=list)
    overall_score: float = 0.0
    passed: bool = True
    reasoning: str = ""

    @property
    def average_score(self) -> float:
        if not self.criteria:
            return self.overall_score
        return sum(c.score for c in self.criteria) / len(self.criteria)


class JudgePort(ABC):
    @abstractmethod
    async def judge(
        self,
        task_description: str,
        output: str,
        criteria: list[str],
        context: str = "",
    ) -> JudgeVerdict: ...
```

#### 2. `weebot/application/eval/__init__.py` (NEW — ~5 lines)

```python
"""Evaluation framework for agent outputs."""
from weebot.application.eval.eval_runner import EvalRunner, EvalTask, EvalResult
```

#### 3. `weebot/application/eval/judges.py` (NEW — ~80 lines)

```python
"""Judge implementations — ModelJudge (LLM) and ScoreJudge (rule-based)."""
from __future__ import annotations

import json
import logging
from typing import Optional

from weebot.application.ports.judge_port import CriterionScore, JudgePort, JudgeVerdict
from weebot.application.ports.llm_port import LLMPort

logger = logging.getLogger(__name__)

_JUDGE_PROMPT = """\
Evaluate the following output against each criterion on a 0-10 scale.

Task: {task}
Output: {output}
Context: {context}

Criteria: {criteria}

For each criterion, provide:
- name: criterion name
- score: 0-10 (10 = perfect)
- reasoning: one sentence

Respond with JSON: {{"criteria": [{{"name": str, "score": float, "reasoning": str}}], "overall": str}}
"""


class ModelJudge(JudgePort):
    def __init__(self, llm: LLMPort, model: Optional[str] = None) -> None:
        self._llm = llm
        self._model = model

    async def judge(
        self,
        task_description: str,
        output: str,
        criteria: list[str],
        context: str = "",
    ) -> JudgeVerdict:
        prompt = _JUDGE_PROMPT.format(
            task=task_description,
            output=output[:3000],
            context=context[:1000],
            criteria=", ".join(criteria),
        )
        try:
            resp = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._model,
                temperature=0.0,
            )
            data = json.loads(resp.content or "{}")
            scores = [
                CriterionScore(
                    name=c.get("name", ""),
                    score=float(c.get("score", 0)),
                    reasoning=c.get("reasoning", ""),
                )
                for c in data.get("criteria", [])
            ]
            verdict = JudgeVerdict(
                criteria=scores,
                overall_score=sum(s.score for s in scores) / len(scores) if scores else 0,
                passed=all(s.score >= 5.0 for s in scores),
                reasoning=data.get("overall", ""),
            )
            return verdict
        except Exception as exc:
            logger.warning("ModelJudge failed: %s — returning default pass", exc)
            return JudgeVerdict(passed=True, reasoning=f"judge error: {exc}")


class ScoreJudge(JudgePort):
    def __init__(self, min_length: int = 50) -> None:
        self._min_length = min_length

    async def judge(
        self, task_description: str, output: str, criteria: list[str], context: str = "",
    ) -> JudgeVerdict:
        scores = []
        for criterion in criteria:
            score = 7.0  # default reasonable score
            if criterion.lower() == "completeness":
                score = min(10.0, len(output) / self._min_length * 5)
            elif criterion.lower() == "correctness":
                score = 7.0 if output.strip() else 0.0
            scores.append(CriterionScore(name=criterion, score=score, reasoning="rule-based"))
        avg = sum(s.score for s in scores) / len(scores) if scores else 0
        return JudgeVerdict(
            criteria=scores, overall_score=avg,
            passed=avg >= 5.0, reasoning="rule-based evaluation",
        )
```

#### 4. `weebot/application/eval/eval_runner.py` (NEW — ~120 lines)

```python
"""EvalRunner — orchestrates evaluation of agent outputs."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from weebot.application.ports.judge_port import JudgePort, JudgeVerdict

logger = logging.getLogger(__name__)


@dataclass
class EvalTask:
    task_id: str
    description: str
    output: str
    criteria: list[str] = field(default_factory=lambda: ["correctness", "completeness"])
    context: str = ""


@dataclass
class EvalResult:
    task_id: str
    verdict: JudgeVerdict
    passed: bool = True

    @property
    def score(self) -> float:
        return self.verdict.average_score


@dataclass
class EvalReport:
    results: list[EvalResult] = field(default_factory=list)

    @property
    def overall_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.score for r in self.results) / len(self.results)

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.passed) / len(self.results)

    @property
    def by_criterion(self) -> dict[str, float]:
        scores: dict[str, list[float]] = {}
        for r in self.results:
            for c in r.verdict.criteria:
                scores.setdefault(c.name, []).append(c.score)
        return {name: sum(s) / len(s) for name, s in scores.items()}


class EvalRunner:
    def __init__(
        self,
        judge: JudgePort,
        parallel: bool = False,
    ) -> None:
        self._judge = judge
        self._parallel = parallel

    async def evaluate(self, tasks: list[EvalTask]) -> EvalReport:
        if self._parallel:
            results = await asyncio.gather(
                *[self._eval_single(t) for t in tasks],
                return_exceptions=True,
            )
            eval_results = [
                r for r in results if isinstance(r, EvalResult)
            ]
        else:
            eval_results = []
            for task in tasks:
                result = await self._eval_single(task)
                eval_results.append(result)

        return EvalReport(results=eval_results)

    async def _eval_single(self, task: EvalTask) -> EvalResult:
        try:
            verdict = await self._judge.judge(
                task_description=task.description,
                output=task.output,
                criteria=task.criteria,
                context=task.context,
            )
            return EvalResult(
                task_id=task.task_id,
                verdict=verdict,
                passed=verdict.passed,
            )
        except Exception as exc:
            logger.warning("EvalRunner: task %s failed: %s", task.task_id, exc)
            return EvalResult(
                task_id=task.task_id,
                verdict=JudgeVerdict(passed=True, reasoning=f"eval error: {exc}"),
                passed=True,
            )
```

### Test Plan

**New file:** `tests/unit/eval/test_eval_runner.py` (~70 lines)

- `test_score_judge_basic` — rule-based scoring
- `test_model_judge_per_criterion` — mock LLM returns per-criterion JSON
- `test_eval_runner_sequential` — runs 3 tasks sequentially
- `test_eval_report_aggregation` — overall_score, pass_rate, by_criterion
- `test_eval_runner_fail_open` — judge error → passed=True

### Risk Mitigation

- **Non-deterministic LLM scoring:** Use `temperature=0.0` and structured JSON. `ScoreJudge` provides deterministic fallback.
- **Token cost:** `StagedEvaluator`'s probe phase filters out obvious passes. Only ambiguous cases reach the LLM judge.

---

## Step 7 — RAG Memory with Port (Improvements #5 + #8)

**Priority:** P2 | **Effort:** ~65 lines | **Risk:** Low | **Dependencies:** None

### Problem

QMD RAG Engine at `qmd_integration/rag_engine.py` provides hybrid BM25+vector search but is not connected to `MemoryFacade`. The original plan had a direct import from application → infrastructure, violating hexagonal architecture.

### Architecture

1. Define `RagPort` in application ports (abstracts RAG retrieval)
2. Implement `QmdRagAdapter` in infrastructure (wraps the QMD RAG Engine)
3. Inject `RagPort` into `MemoryFacade` as a 5th backend
4. `MemoryFacade.recall()` routes to RAG alongside the existing 4 backends

### Files

#### 1. `weebot/application/ports/rag_port.py` (NEW — ~15 lines)

```python
"""Port for Retrieval-Augmented Generation backends."""
from __future__ import annotations

from abc import ABC, abstractmethod


class RagPort(ABC):
    @abstractmethod
    async def search(self, query: str, top_k: int = 5) -> list[str]:
        """Search the RAG index and return ranked text chunks."""
        ...
```

#### 2. `weebot/infrastructure/adapters/qmd_rag_adapter.py` (NEW — ~35 lines)

```python
"""QMD RAG adapter — wraps the QMD RAG Engine behind the RagPort interface."""
from __future__ import annotations

import logging
from typing import Optional

from weebot.application.ports.rag_port import RagPort

logger = logging.getLogger(__name__)


class QmdRagAdapter(RagPort):
    def __init__(self, rag_engine: Optional[object] = None) -> None:
        self._engine = rag_engine

    async def search(self, query: str, top_k: int = 5) -> list[str]:
        if self._engine is None:
            return []
        try:
            search_method = getattr(self._engine, "search", None)
            if search_method is None:
                search_method = getattr(self._engine, "query", None)
            if search_method is None:
                logger.warning("QMD RAG engine has no search/query method")
                return []

            import asyncio
            if asyncio.iscoroutinefunction(search_method):
                results = await search_method(query, top_k=top_k)
            else:
                results = search_method(query, top_k=top_k)

            if isinstance(results, list):
                return [str(r) for r in results[:top_k]]
            return [str(results)] if results else []
        except Exception as exc:
            logger.warning("QMD RAG search failed: %s", exc)
            return []
```

#### 3. `weebot/application/services/memory_facade.py` — EDIT (~15 lines)

Add `rag` parameter to `__init__` (after `persistent_memory` at line 38):

```python
        rag: Optional[Any] = None,  # RagPort
```

Store as `self._rag = rag`.

Add RAG routing in `recall()`, after the PersistentMemory block (after line 97):

```python
        # 5. RAG — semantic search via RagPort
        if self._rag is not None:
            try:
                rag_results = await self._rag.search(query, top_k=top_k)
                for chunk in rag_results:
                    results.append({"source": "rag", "content": chunk, "confidence": 0.85})
            except Exception:
                logger.debug("RAG search failed", exc_info=True)
```

### Test Plan

- Unit test `QmdRagAdapter` with a mock engine
- Unit test `MemoryFacade.recall()` includes RAG results when `rag` is set
- Unit test `MemoryFacade.recall()` degrades gracefully when `rag` is None

### Risk

Low. RAG is additive. If `RagPort` is not configured (None), no retrieval happens. Follows the existing graceful degradation pattern of `MemoryFacade`.

---

## Cross-Cutting Concerns

### Hexagonal Architecture Compliance

Every new file must satisfy the dependency rule:

| Layer | Can import from | Cannot import from |
|---|---|---|
| Domain (`domain/`) | Python stdlib only | Application, Infrastructure, Interfaces |
| Application (`application/`) | Domain, Python stdlib | Infrastructure, Interfaces |
| Infrastructure (`infrastructure/`) | Application, Domain, Python stdlib | Interfaces |
| Interfaces (`interfaces/`) | All layers | — |

**Verification:** After each step, run:
```bash
python -c "
import ast, sys, pathlib
for f in pathlib.Path('weebot/application').rglob('*.py'):
    tree = ast.parse(f.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, 'module', '') or ''
            if 'infrastructure' in mod or 'interfaces' in mod:
                print(f'VIOLATION: {f}:{node.lineno} imports {mod}')
                sys.exit(1)
print('OK: no hexagonal violations')
"
```

### Type Hints

All new public methods must have complete type annotations. All new dataclasses use `@dataclass(frozen=True)` where possible (immutability by default per coding style rules).

### Error Handling

All new LLM calls follow the fail-open pattern: catch `Exception`, log a warning, and return a default "pass" result. Agent flow must never crash due to an evaluation or middleware failure.

### Backward Compatibility

Every new feature is gated on an `Optional` parameter defaulting to `None`. When `None`, behavior is identical to the current codebase. No existing test should break after any step.

### Logging

Use `logger = logging.getLogger(__name__)` at module level. Log at `INFO` for state transitions and evaluation results. Log at `WARNING` for failures that trigger fallback behavior. Log at `DEBUG` for detailed diagnostic output.

---

## Validation Protocol

After **each** step in the implementation sequence:

1. **Existing tests pass:**
   ```bash
   pytest tests/ -v --timeout=30
   ```

2. **New tests pass:**
   ```bash
   pytest tests/unit/<new_test_file>.py -v
   ```

3. **No hexagonal violations** (run the script above)

4. **Type check (if mypy/pyright configured):**
   ```bash
   mypy weebot/application/<changed_module> --ignore-missing-imports
   ```

5. **No new dependencies:**
   ```bash
   git diff requirements.txt  # should be empty
   ```

6. **Health check:**
   ```bash
   python -m cli.main health
   ```

After **all** steps complete:

7. **Full test suite with coverage:**
   ```bash
   pytest tests/ --cov=weebot --cov-report=term-missing -v
   ```

8. **Integration smoke test:**
   ```bash
   python -m cli.main flow run "list files in the current directory"
   ```

---

## Summary

| Step | Improvement | Files Changed | Lines | Risk |
|------|------------|---------------|-------|------|
| 1 | Pre-call compaction | 1 edit | 3 | None |
| 2 | StepProgressEvaluation | 2 new + 3 edits | ~160 | Medium |
| 3 | Middleware chain | 1 new + 3 edits | ~80 | Low |
| 4 | ToolApprovalRequest UX | 3 edits | ~47 | Low |
| 5 | Composable termination | 3 new + 4 edits | ~165 | Low |
| 6 | EvalRunner | 3 new + 0 edits | ~240 | Medium |
| 7 | RAG with port | 2 new + 1 edit | ~65 | Low |
| **Total** | | **11 new + 14 edits** | **~760** | |
