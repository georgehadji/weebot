# Multi-Agent Patterns Integration Plan

**Source:** [`victordibia/designing-multiagent-systems`](https://github.com/victordibia/designing-multiagent-systems) (PicoAgents v0.4.0 — MIT license)
**Target:** Weebot
**Architecture:** Hexagonal (Clean Architecture). All changes must respect the dependency rule: `Interfaces → Infrastructure → Application → Domain`

---

## Context: What the Audit Found

A cross-reference audit of PicoAgents against Weebot identified eight high-ROI transfers. Four were in the original draft; two were missing P0/P1 improvements now included; two were fundamentally misdiagnosed and are corrected below.

| # | Improvement | PicoAgents Source | Weebot Current State | Gap |
|---|---|---|---|---|
| **1** | Wire Middleware into LLM call path | `picoagents/middleware/` — composable chain wrapped around every LLM request | `Middleware` ABC exists at [`middleware/base.py`](../weebot/application/middleware/base.py) but **never invoked** by executor (0 refs in `weebot/application/agents/`) | The ABC and `SubAgentMiddleware` exist — connection needed |
| **2** | Composable termination conditions | `picoagents/termination/` — 9 strategies, `CompositeTermination` with AND/OR | `MAX_EXECUTOR_STEPS=50` hardcoded at [`_base.py:18`](../weebot/application/agents/executor/_base.py:18). `TokenBudgetMonitor` is observability-only | No token-budget/timeout/text-mention termination. No composition |
| **3** | EvalRunner with multi-criterion LLM-as-judge | `picoagents/eval/` — `ModelJudge` with per-`CriterionScore` (name + score + reasoning), `EvalRunner` aggregates | `StagedEvaluator` at [`staged_evaluator.py`](../weebot/application/services/staged_evaluator.py) — probe-then-full, but caller provides eval_fn. No built-in judge, no per-criterion scoring | Full eval framework needed |
| **4** | Pre-call compaction (not post-call) | `picoagents/agents/_base.py:195` — `_prepare_llm_messages()` applies compaction BEFORE assembling messages, so current turn benefits | `_maybe_compress()` at [`_base.py:306`](../weebot/application/agents/executor/_base.py:306) fires via `_track_usage_and_maybe_compress()` AFTER the LLM call (lines 474/484/496). Compaction result only visible NEXT turn | Move compaction to before-call — 3-line fix |
| **5** | RAG memory in executor retrieval path (corrected) | `picoagents/memory/` — `ChromaDBMemory` injected before LLM call | QMD RAG Engine at [`qmd_integration/rag_engine.py`](../weebot/qmd_integration/rag_engine.py) — production hybrid BM25+vector. NOT wired into `MemoryFacade` | Add `RagPort` to application ports, implement adapter, wire into facade |
| **6** | StepProgressEvaluation (NEW P0) | `picoagents/orchestration/_plan.py` — after each step, checks completion against plan, triggers replan on divergence | `CompletedState` at [`completed.py`](../weebot/application/flows/states/completed.py) has post-completion analysis (`TrustReport`, `RetentionReview`, `DreamScan`) but no per-step progress evaluation during execution | Evaluate per-step, trigger early replan on regression |
| **7** | ToolApprovalRequest UX (NEW P1) | `picoagents/middleware/` — `ToolApprovalEvent` pauses execution, yields event to caller, waits for user resume | `BashGuard` + [`approval_policy.py`](../weebot/core/approval_policy.py) classify commands as `ALWAYS_ASK` / `DENY`. But the pause/resume UX is the `WaitForUserEvent` in `ExecutingState` — different abstraction | Unify BashGuard classification with a clean pause/resume event for DANGEROUS tools |
| **8** | RAGMemory — needs a port (CORRECTION) | Original plan had `RagMemory.retrieve()` doing `from weebot.qmd_integration.rag_engine import QMDRagEngine` — application importing infrastructure. Violates hexagonal architecture | Correct approach: define `RagPort` in application ports, implement `QmdRagAdapter` in infrastructure, inject into `MemoryFacade` | One new port + one new adapter |

**Bonus insight:** Weebot is ahead of PicoAgents in four areas: BashGuard's 4-tier safety, ModelCascadeService with circuit breakers + live model rescue, the full skill ecosystem, and plan-stuck detection via `PlanHistory` fingerprinting. These are NOT gaps — no changes needed.

---

## Improvement 1 — Wire Middleware Chain Into Executor LLM Calls (P0 — HIGH ROI)

### Problem

The `Middleware` ABC at [`weebot/application/middleware/base.py`](../weebot/application/middleware/base.py) defines `before_request`, `after_response`, `after_tool_call`. `SubAgentMiddleware` at [`middleware/subagent.py`](../weebot/application/middleware/subagent.py) injects a `task` tool. The ABC has been designed but **never connected to the executor's LLM call path** — zero middleware references in `weebot/application/agents/`.

### Changes

**File 1: `weebot/application/middleware/chain.py`** (new, ~50 lines)

`MiddlewareChain` — stateless ordered list of `Middleware` instances. Three methods: `apply_before_request(messages, tools, step_id, step_description) → (messages, tools)`, `apply_after_response(content, tool_calls, ...) → (content, tool_calls)`, `apply_after_tool_call(...) → ToolCallResult`. Each runs all middleware in declaration order, threading a state dict through.

**File 2: `weebot/application/agents/executor/_base.py`** — 4 insertion points (~30 lines total)

(A) Add to `__init__` (after line 160):
```python
        middleware_chain: Optional["MiddlewareChain"] = None,
```
Store as `self._middleware_chain`.

(B) In `execute_step()`, before `_call_with_cascade()` (insert after messages assembled, around line 740):
```python
            if self._middleware_chain is not None and not self._middleware_chain.is_empty():
                msgs_for_mw = [{"role": "system", "content": self._system_prompt}] + list(self._conversation_buffer)
                filtered_msgs, filtered_tools = await self._middleware_chain.apply_before_request(
                    messages=msgs_for_mw,
                    tools=self._tools.to_params(),
                    step_id=step.id,
                    step_description=step.description,
                )
                # Rebuild messages with potentially injected tools
                messages = filtered_msgs
```

(C) After `_call_with_cascade()` returns, around line 760:
```python
            if self._middleware_chain is not None and not self._middleware_chain.is_empty():
                modified_content, modified_tool_calls = await self._middleware_chain.apply_after_response(
                    content=assistant_content,
                    tool_calls=response.tool_calls or [],
                    messages=messages,
                    tools=self._tools.to_params(),
                )
                assistant_content = modified_content or assistant_content
                if response.tool_calls:
                    response.tool_calls = modified_tool_calls
```

(D) After each tool result in `_execute_tool_batch()` results loop (around line 815):
```python
            if self._middleware_chain is not None and not self._middleware_chain.is_empty():
                result = await self._middleware_chain.apply_after_tool_call(
                    tool_name=tool_name,
                    arguments=event_args,
                    output=result.output or "",
                    error=result.error,
                    is_error=result.is_error,
                )
```

### Test Plan

**`tests/unit/tools/test_middleware_chain.py`** (new, ~60 lines): empty chain returns unchanged, single middleware modifies tools, ordered execution, after_tool_call intercepts.

### Risk: Low. The `SubAgentMiddleware` already handles `task` tool collision. No performance impact — per-LLM-call overhead < 1ms for sync middleware.

---

## Improvement 4 (CORRECTED) — Move Compaction to Pre-Call

### Problem (Corrected)

Compaction IS wired — `_maybe_compress()` at [`_base.py:306`](../weebot/application/agents/executor/_base.py:306) is called via `_track_usage_and_maybe_compress(resp)` on lines 474, 484, and 496 — all AFTER the LLM response returns. The compacted conversation buffer only benefits the *next* LLM call, not the one just made. If the current call overflows the context window, it gets a truncated response or an error before compaction runs.

PicoAgents applies compaction at `_base.py:195` BEFORE assembling the messages array, so every LLM call sees compacted context.

### Changes

**File: `weebot/application/agents/executor/_base.py`** — 3-line insertion in `execute_step()`

Before the message-assembly block (before line 740), add:
```python
            # ── Pre-call compaction: ensure the LLM sees a compacted context ──
            await self._maybe_compress()
```

That's it. `_maybe_compress()` already checks `self._auto_compress` and the threshold. Moving it from post-call to pre-call means compaction benefits the current turn, not the next one.

**Keep the post-call calls on lines 474/484/496** — they still serve to update token counters. The pre-call call adds the compaction step that actually shrinks the buffer before the LLM sees it.

### Risk: None. `_maybe_compress()` is idempotent — calling it twice (pre + post) is safe. Token threshold check prevents compaction when not needed.

---

## Improvement 6 (NEW P0) — StepProgressEvaluation

### Problem

The `PlanActFlow` at [`plan_act_flow.py:250-400`](../weebot/application/flows/plan_act_flow.py:250) emits `StepEvent(status=StepStatus.COMPLETED)` after each step, then transitions to `UpdatingState`. But there's no evaluation of whether the step actually made progress toward the plan goal. The `PlanHistory` fingerprinting only detects *identical plan regressions*, not *step-level regressions* (a step completes but the output is wrong or regresses previous work).

PicoAgents' `PlanBasedOrchestrator` evaluates after each step: checks output against expected, triggers replan on divergence, and scores step quality. This is the single highest-impact gap — it prevents the "silently wrong" failure mode where an agent completes all steps but the result is incorrect and undetected.

### Architectural Approach

Add a `StepEvaluatorPort` to the application ports layer. The `ExecutingState` at [`executing.py`](../weebot/application/flows/states/executing.py) calls it after each step completes and before transitioning to `UpdatingState`. If the evaluator reports regression (score < threshold), the flow transitions directly to `UpdatingState` with a `REPLAN_NEEDED` flag instead of continuing to `VerifyingState`.

The evaluator is a port, not a concrete implementation — enabling multiple strategies:
- **NoOp evaluator** — current behavior (always pass)
- **LLM-as-judge evaluator** — calls cheap model to score step against expected output
- **Regression detector** — compares current output against previous step outputs (detects regressions in refactoring/editing)

### Files

| File | Change |
|---|---|
| `weebot/application/ports/step_evaluator_port.py` | New — `StepEvaluatorPort` ABC with `evaluate(step, output, plan) → StepEvaluation` (~25 lines) |
| `weebot/application/services/step_evaluator.py` | New — `LLMStepEvaluator` implementation (~80 lines) |
| `weebot/application/flows/states/executing.py` | Edit — call `evaluator.evaluate()` after step completes, branch to `UpdatingState(force_replan=True)` on regression (~15 lines) |
| `weebot/application/flows/plan_act_flow.py` | Edit — inject `StepEvaluatorPort` into flow init, pass to `ExecutingState` (~8 lines) |

### Design

```python
# weebot/application/ports/step_evaluator_port.py

@dataclass
class StepEvaluation:
    step_id: str
    score: float                # 0.0–1.0
    passed: bool                # True if score >= threshold
    regression_detected: bool   # Output regresses previous work
    reasoning: str              # 1-sentence justification
    recommendations: list[str]  # What to do differently on replan

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

### Test Plan

**`tests/unit/tools/test_step_evaluator.py`** (new, ~50 lines): no_regression_when_output_improves, regression_detected_when_output_reverts, threshold_failure_triggers_replan.

### Risk: Medium. An over-sensitive evaluator could cause infinite replan loops. Mitigated by `PlanHistory` which still catches 3 consecutive similar plans.

---

## Improvement 7 (NEW P1) — ToolApprovalRequest UX

### Problem

Weebot has BashGuard's 4-tier risk classification at [`bash_guard.py`](../weebot/core/bash_guard.py) and `ApprovalPolicy` at [`approval_policy.py`](../weebot/core/approval_policy.py) with `ALWAYS_ASK` mode. But the UX for pausing and resuming on a DANGEROUS tool call is:
1. BashGuard classifies → DANGEROUS
2. `ExecApprovalPolicy` returns `requires_confirmation=True`
3. The tool execution returns an error like "requires user confirmation"
4. The LLM sees this error and may retry or give up

PicoAgents has a cleaner pattern: emit a `ToolApprovalEvent` that pauses the agent loop, yields control back to the caller (CLI/Web UI), and resumes when the user approves. The LLM never sees a "requires confirmation" error — it sees a clean tool result.

### Architectural Approach

Add `ToolApprovalEvent` to the event model. When BashGuard classifies a command as DANGEROUS and the policy returns `requires_confirmation=True`, emit a `ToolApprovalEvent` instead of returning an error. The flow pauses at `ExecutingState`, the CLI/UI shows the approval prompt, and on resume (user types "yes"), the tool executes and the result is injected back into the conversation.

This requires no changes to BashGuard or the approval policy — only to how the "requires confirmation" signal is surfaced in the event stream.

### Files

| File | Change |
|---|---|
| `weebot/domain/models/event.py` | Edit — add `ToolApprovalEvent` dataclass (~12 lines) |
| `weebot/application/agents/executor/_base.py` | Edit — in `_execute_tool_batch()`, check `requires_confirmation` before executing, emit `ToolApprovalEvent` if true (~15 lines) |
| `weebot/application/flows/states/executing.py` | Edit — handle `ToolApprovalEvent` in the event loop: pause, yield wait event, resume (~20 lines) |

### Design

```python
@dataclass
class ToolApprovalEvent(AgentEvent):
    type: str = "tool_approval"
    tool_name: str
    arguments: dict
    risk_level: str          # "DANGEROUS" or "SUSPICIOUS"
    reason: str              # e.g. "rm -rf detected — requires confirmation"
    prompt: str              # e.g. "Allow this command? (yes/no)"
```

### Risk: Low. `ToolApprovalEvent` is additive — existing error-return path stays as fallback. BashGuard classification unchanged.

---

## Improvement 2 — Composable Termination Conditions (P1)

### Problem

`MAX_EXECUTOR_STEPS=50` hardcoded at [`_base.py:18`](../weebot/application/agents/executor/_base.py:18) with `StepBudget` wrapper. `max_iterations` in PlanActFlow loop at [`plan_act_flow.py:486`](../weebot/application/flows/plan_act_flow.py:486). No token-budget termination, no wall-clock timeout, no text-mention trigger, and no composition.

`TokenBudgetMonitor` at [`token_budget_monitor.py`](../weebot/application/services/token_budget_monitor.py) tracks usage but is pure observability — no `should_terminate()`.

### Architectural Approach

New `termination/` package at the application layer. Strategies implement a common ABC. `CompositeTermination` supports AND/OR. PlanActFlow checks termination at the top of each loop iteration before dispatching.

### Files

| File | Change |
|---|---|
| `weebot/application/termination/__init__.py` | New (~5 lines) |
| `weebot/application/termination/base.py` | New — `TerminationCondition` ABC, `TerminationContext`, `TerminationResult` (~40 lines) |
| `weebot/application/termination/conditions.py` | New — `MaxIteration`, `TokenBudget`, `WallClock`, `TextMention`, `Composite` (~100 lines) |
| `weebot/application/services/token_budget_monitor.py` | Edit — add `should_terminate(threshold=0.95) → bool` (5 lines) |
| `weebot/application/flows/plan_act_flow.py` | Edit — inject `termination_conditions: list[TerminationCondition]`, check in `run()` loop before state dispatch (~15 lines) |
| `weebot/application/flows/states/completed.py` | Edit — accept `termination_reason: str` and log (~5 lines) |

### Risk: Low. All conditions are O(1) sync checks except `TextMention` (scans last 5 messages).

---

## Improvement 3 — EvalRunner with Per-Criterion Scoring (P1)

### Problem

`StagedEvaluator` at [`staged_evaluator.py`](../weebot/application/services/staged_evaluator.py) is a cost-saving probe layer — caller provides `eval_fn`. No built-in judge, no per-criterion scoring, no metrics pipeline.

PicoAgents' `EvalRunner` provides `ModelJudge` with `CriterionScore(name, score, reasoning)` per criterion. This enables fine-grained evaluation: "correctness: 0.8, completeness: 0.6, specificity: 0.9".

### Architectural Approach

Extend `StagedEvaluator` — keep the probe-then-full cost optimization. Build `EvalRunner` on top with:
- `JudgePort` (application port) with two implementations: `ModelJudge`, `ScoreJudge`
- Per-criterion `CriterionScore` with reasoning per criterion, not one float
- `EvalReport` aggregating by criterion and overall

### Files

| File | Change |
|---|---|
| `weebot/application/ports/judge_port.py` | New — `JudgePort`, `CriterionScore`, `JudgeVerdict` (~35 lines) |
| `weebot/application/eval/__init__.py` | New (~5 lines) |
| `weebot/application/eval/eval_runner.py` | New — `EvalRunner`, `EvalTask`, `EvalResult`, `EvalReport` (~120 lines) |
| `weebot/application/eval/judges.py` | New — `ModelJudge`, `ScoreJudge` (~80 lines) |

### Risk: Medium. LLM-as-judge is non-deterministic and costs tokens. Mitigated by `StagedEvaluator` probe phase — only tasks that pass probe get expensive LLM evaluation.

---

## Improvement 5 + 8 — RAG Memory with Proper Port (CORRECTED — P2)

### Problem (Corrected)

The QMD RAG Engine at [`qmd_integration/rag_engine.py`](../weebot/qmd_integration/rag_engine.py) provides hybrid BM25+vector search but is not connected to `MemoryFacade`. The original plan had `RagMemory.retrieve()` doing `from weebot.qmd_integration.rag_engine import QMDRagEngine` — an **application layer importing infrastructure**, violating hexagonal architecture.

### Corrected Approach

1. Define `RagPort` (application port) with `search(query: str, top_k: int) → list[str]`
2. Implement `QmdRagAdapter` (infrastructure adapter) wrapping the QMD RAG engine
3. Inject `RagPort` into `MemoryFacade` as a 5th backend
4. `MemoryFacade.recall()` routes to RAG alongside session/working/episodic/persistent memory

This follows the existing pattern: `MemoryFacade` already depends on domain services (`SessionMemory`, `WorkingMemory`) and optional `Any`-typed backends for episodic/persistent. Adding a typed port is cleaner.

### Files

| File | Change |
|---|---|
| `weebot/application/ports/rag_port.py` | New — `RagPort` ABC with `search(query, top_k) → list[str]` (~10 lines) |
| `weebot/infrastructure/adapters/qmd_rag_adapter.py` | New — `QmdRagAdapter(RagPort)` wraps `qmd_integration.rag_engine.QMDRagEngine` (~35 lines) |
| `weebot/application/services/memory_facade.py` | Edit — add `rag: Optional[RagPort]` to `__init__`, add RAG routing in `recall()` (~15 lines) |
| `weebot/application/agents/executor/_base.py` | Edit — add RAG retrieval call to system prompt assembly chain (~5 lines) |

### Risk: Low. RAG is additive — if `RagPort` is not configured (None), no retrieval happens (graceful degradation).

---

## Implementation Sequence (Prioritized by ROI)

```
Step 1 — #4 Pre-call compaction       ROI: P0  Effort: 3 lines   Risk: None
Step 2 — #6 StepProgressEvaluation   ROI: P0  Effort: ~160 lines Risk: Medium
Step 3 — #1 Middleware chain          ROI: P0  Effort: ~80 lines  Risk: Low
Step 4 — #7 ToolApprovalRequest       ROI: P1  Effort: ~47 lines  Risk: Low
Step 5 — #2 Termination conditions    ROI: P1  Effort: ~165 lines Risk: Low
Step 6 — #3 EvalRunner                ROI: P1  Effort: ~240 lines Risk: Medium
Step 7 — #5+8 RAG with proper port    ROI: P2  Effort: ~65 lines  Risk: Low
```

Total: ~760 lines across 22 files (13 new, 9 edits). No new Python dependencies.

---

## File Change Summary

| File | Change | Step |
|---|---|---|
| `weebot/application/agents/executor/_base.py` | Edit (~50 lines: pre-call compaction + middleware wiring + ToolApprovalEvent + RAG) | 1,3,4,7 |
| `weebot/application/middleware/chain.py` | New (~50 lines) | 3 |
| `weebot/application/termination/__init__.py` | New (~5 lines) | 5 |
| `weebot/application/termination/base.py` | New (~40 lines) | 5 |
| `weebot/application/termination/conditions.py` | New (~100 lines) | 5 |
| `weebot/application/services/token_budget_monitor.py` | Edit (~5 lines) | 5 |
| `weebot/application/flows/plan_act_flow.py` | Edit (~23 lines) | 2,5,6 |
| `weebot/application/flows/states/completed.py` | Edit (~5 lines) | 5 |
| `weebot/application/flows/states/executing.py` | Edit (~35 lines) | 6,7 |
| `weebot/application/ports/step_evaluator_port.py` | New (~25 lines) | 6 |
| `weebot/application/services/step_evaluator.py` | New (~80 lines) | 6 |
| `weebot/domain/models/event.py` | Edit (~12 lines) | 7 |
| `weebot/application/ports/judge_port.py` | New (~35 lines) | 3 (eval) |
| `weebot/application/eval/__init__.py` | New (~5 lines) | 3 (eval) |
| `weebot/application/eval/eval_runner.py` | New (~120 lines) | 3 (eval) |
| `weebot/application/eval/judges.py` | New (~80 lines) | 3 (eval) |
| `weebot/application/ports/rag_port.py` | New (~10 lines) | 7 |
| `weebot/infrastructure/adapters/qmd_rag_adapter.py` | New (~35 lines) | 7 |
| `weebot/application/services/memory_facade.py` | Edit (~15 lines) | 7 |
| **Tests** | |
| `tests/unit/tools/test_middleware_chain.py` | New (~60 lines) | 3 |
| `tests/unit/tools/test_termination.py` | New (~90 lines) | 5 |
| `tests/unit/tools/test_step_evaluator.py` | New (~50 lines) | 6 |
| `tests/unit/tools/test_eval_runner.py` | New (~70 lines) | 3 (eval) |

---

## Validation Checklist

After each step:

- [ ] All existing tests pass (`pytest tests/ -v`)
- [ ] New tests added and passing
- [ ] Hexagonal architecture: no inner-layer → outer-layer imports from new code
- [ ] Type hints on all new public methods
- [ ] Docstrings on all new public classes
- [ ] No new Python package dependencies
