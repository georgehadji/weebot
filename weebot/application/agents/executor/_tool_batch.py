"""Tool-call batches inside one executor step (WB-06, phase 4.2).

`ExecutorStep.execute_step` ran the whole tool phase inline: pre-flight every call for
repeats, run the batch concurrently, then walk the results deciding, per result, whether
the trajectory is degenerating, whether the same policy error has now happened too often,
what middleware wants to change, and whether the step should stop.

None of that is step *orchestration*; it is one batch's policy, with state that survives
across turns of the same step (the error-class streak, the semantic-loop recovery count).
That state is the reason this is a class rather than a function: constructing a
`ToolBatchRunner` once per step is what makes the counters' lifetime explicit instead of
six locals threaded through a 400-line loop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from weebot.application.agents.executor._error_handler import (
    classify_tool_error,
    is_expected_failure,
    parse_args_for_event,
    tool_signature,
)
from weebot.application.agents.executor._loop_detectors import (
    DuplicateResultStub,
    GuardConfig,
    Verdict,
)
from weebot.application.agents.executor._step_result_handler import feed_vision, pause_events
from weebot.application.services.spillover import spill_over_budget, turn_budget
from weebot.core.log_context import session_id_var
from weebot.domain.models.event import (
    AgentEvent,
    ErrorEvent,
    MessageEvent,
    ToolEvent,
    ToolStatus,
    WaitForUserEvent,
)
from weebot.domain.models.tool_result import ToolResult
from weebot.domain.models.trajectory import TrajectoryHealth

if TYPE_CHECKING:
    from weebot.application.agents.executor._base import ExecutorAgent
    from weebot.domain.models.plan import Step

logger = logging.getLogger(__name__)

# How many consecutive identical error classes before the step asks a human.
_MAX_SAME_ERROR_CLASS = 3
# SEMANTIC_LOOP gets this many recovery hints before the step aborts.
_MAX_SEMANTIC_LOOP_RECOVERIES = 2

# Trajectory healths that abort the step outright.
_AUTO_ABORT_HEALTH = frozenset(
    {
        TrajectoryHealth.TERMINAL,
        TrajectoryHealth.STAGNATING,
        TrajectoryHealth.EXHAUSTED,
    }
)

_POLICY_ERROR_CLASSES = (
    "security_blocked",
    "policy_denied",
    "confirmation_required",
)


def _merge_middleware_result(result: ToolResult, mw: Any) -> ToolResult:
    """The tool result with middleware's output (and error, if it set one).

    Built with ``dataclasses.replace``: ``is_error`` is a property, so passing it
    to ``ToolResult(...)`` raised TypeError, and data/metadata were dropped (F64).
    """
    import dataclasses

    error = mw.error or result.error
    if mw.is_error and not error:
        error = "Tool output rejected by middleware"
    return dataclasses.replace(result, output=mw.output, error=error, success=error is None)


def _called_event(tool_call: dict, event_args: dict, result: ToolResult) -> ToolEvent:
    tool_name = tool_call["function"]["name"]
    return ToolEvent(
        tool_call_id=tool_call["id"],
        tool_name=tool_name,
        function_name=tool_name,
        function_args=event_args,
        status=ToolStatus.CALLED,
        result=str(result),
        is_error=bool(result.is_error),
    )


@dataclass
class BatchOutcome:
    """The mutable half of a batch: what the caller's loop must react to."""

    abort_step: bool = False
    paused: bool = False
    """The step stopped for a human (an approval or a question), so it has not finished."""
    loop_error: str | None = None
    step_result: str = ""
    terminate: bool = False
    events: list[AgentEvent] = field(default_factory=list)


class ToolBatchRunner:
    """Runs one step's tool batches, remembering what happened in the earlier ones."""

    def __init__(self, config: GuardConfig | None = None) -> None:
        self._stubs = DuplicateResultStub((config or GuardConfig()).stub_min_chars)
        self.tool_calls_attempted = 0
        self.tool_calls_succeeded = 0
        self._semantic_loop_recoveries = 0
        self._last_error_class: str | None = None
        self._error_class_streak: dict[str, int] = {}

    async def run(
        self,
        executor: ExecutorAgent,
        step: Step,
        tool_calls: list[dict],
        guard: Any,
        *,
        step_result: str,
        notes: list[str] | None = None,
    ) -> BatchOutcome:
        """Pre-flight, execute and process one batch of tool calls.

        *notes* are recovery hints the caller already has; they follow the tool messages.
        """
        outcome = BatchOutcome(step_result=step_result)
        hints: list[str] = list(notes or [])

        prepared = self._preflight(executor, step, tool_calls, guard, outcome, hints)
        if outcome.abort_step:
            return outcome

        results = await executor._tool_executor.execute_tool_batch(prepared)
        assert len(results) == len(prepared), (
            f"Mismatched result count {len(results)} vs tool call count {len(prepared)}"
        )

        store = executor._spillover_store
        if store is not None:
            await spill_over_budget(
                store,
                session_id_var.get() or "unknown",
                [tc["function"]["name"] for tc in prepared],
                results,
                turn_budget(),
            )

        for tool_call, result in zip(prepared, results, strict=False):
            await self._process_one(executor, step, tool_call, result, guard, outcome, hints)
            if outcome.abort_step:
                break

        # After the tool messages: nothing may sit between a call and its answer.
        for hint in hints:
            executor._conversation_buffer.append(
                {"role": "system", "content": f"[RECOVERY] {hint}"}
            )
        return outcome

    # ── pre-flight ───────────────────────────────────────────────────────────

    def _preflight(
        self,
        executor: ExecutorAgent,
        step: Step,
        tool_calls: list[dict],
        guard: Any,
        outcome: BatchOutcome,
        hints: list[str],
    ) -> list[dict]:
        """Record signatures, emit CALLING, and stop on an identical repeat or a cycle."""
        prepared: list[dict] = []
        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            raw_arguments = tool_call["function"].get("arguments", "{}")
            cycle = guard.record_tool_call(tool_signature(tool_name, raw_arguments))

            reason = None
            if guard.is_tool_signature_loop():
                reason = f"repeated identical tool call '{tool_name}'"
            elif cycle is not None and cycle.kind is Verdict.STOP:
                reason = cycle.message
            if reason:
                outcome.loop_error = guard.build_stuck_error(
                    reason=reason,
                    step_description=step.description,
                )
                outcome.events.append(ErrorEvent(error=outcome.loop_error))
                outcome.abort_step = True
                return prepared
            if cycle is not None:
                hints.append(cycle.message)
            outcome.events.append(
                ToolEvent(
                    tool_call_id=tool_call["id"],
                    tool_name=tool_name,
                    function_name=tool_name,
                    function_args=parse_args_for_event(raw_arguments),
                    status=ToolStatus.CALLING,
                )
            )
            prepared.append(tool_call)
        return prepared

    # ── one result ───────────────────────────────────────────────────────────

    async def _process_one(
        self,
        executor: ExecutorAgent,
        step: Step,
        tool_call: dict,
        result: ToolResult,
        guard: Any,
        outcome: BatchOutcome,
        hints: list[str],
    ) -> None:
        tool_name = tool_call["function"]["name"]
        raw_arguments = tool_call["function"].get("arguments", "{}")
        event_args = parse_args_for_event(raw_arguments)
        signature = tool_signature(tool_name, raw_arguments)

        self.tool_calls_attempted += 1
        if not result.is_error:
            self.tool_calls_succeeded += 1

        if await self._degenerating(
            executor, step, signature, result=result, outcome=outcome, hints=hints
        ):
            # The step stops here, but the result that stopped it is still shown.
            called = _called_event(tool_call, event_args, result)
            outcome.events.insert(len(outcome.events) - 1, called)
            return
        if self._policy_error_loop(step, result, outcome):
            return
        if self._denial_loop(step, result, outcome):
            return

        result = await self._middleware(executor, tool_name, event_args, result)
        if result is None:
            return

        outcome.events.append(_called_event(tool_call, event_args, result))

        if result.data:
            executor._facts[tool_name] = result.data
            paused = pause_events(result, tool_name)
            if paused:
                outcome.events.extend(paused)
                outcome.abort_step = True
                outcome.paused = True
                return

        if tool_name == "terminate":
            logger.info("Terminate tool called, task completed")
            executor._should_terminate = True
            outcome.step_result = executor._maybe_truncate_ponytail(
                result.output or "Task completed"
            )
            outcome.events.append(MessageEvent(role="assistant", message=outcome.step_result))
            executor._step_budget.refund(executor._step_budget.remaining)
            outcome.terminate = True
            outcome.abort_step = True
            return

        # A repeat of an earlier result becomes a pointer; the UI event above kept the text.
        stub = None if result.is_error else self._stubs.observe(
            self.tool_calls_attempted, result.output or ""
        )
        tool_content = stub or await executor._present_tool_output(tool_name, result)
        executor._conversation_buffer.append(
            {"role": "tool", "content": tool_content, "tool_call_id": tool_call["id"]}
        )

        await feed_vision(executor, tool_name, result, step.description)

    # ── the three policies one result can trip ───────────────────────────────

    async def _degenerating(
        self,
        executor: ExecutorAgent,
        step: Step,
        signature: str,
        *,
        result: ToolResult,
        outcome: BatchOutcome,
        hints: list[str],
    ) -> bool:
        """Tier 1.3 TrajectoryMonitor. True when the step must stop at this result."""
        if executor._trajectory_monitor is None:
            return False

        diagnosis = executor._trajectory_monitor.diagnose(
            step_id=step.id,
            tool_signature=signature,
            tool_output=result.output or "",
            error=result.error if result.is_error else None,
            step_result=outcome.step_result if outcome.step_result else None,
            total_budget=executor._max_steps,
            used_budget=self.tool_calls_attempted,
            available_tools=(list(executor._tools._tools.keys()) if executor._tools else None),
        )
        if diagnosis.recovery_message:
            hints.append(diagnosis.recovery_message)

        level = logger.debug if diagnosis.health == TrajectoryHealth.HEALTHY else logger.warning
        level(
            "Trajectory %s for step %s: %s",
            diagnosis.health.value,
            step.id,
            diagnosis.detail,
        )

        # Give SEMANTIC_LOOP a couple of recovery attempts before aborting; the monitor
        # already injected the recovery message above.
        if diagnosis.health == TrajectoryHealth.SEMANTIC_LOOP:
            if self._semantic_loop_recoveries < _MAX_SEMANTIC_LOOP_RECOVERIES:
                self._semantic_loop_recoveries += 1
                logger.warning(
                    "SEMANTIC_LOOP for step %s — injecting recovery hint (attempt %d/%d)",
                    step.id,
                    self._semantic_loop_recoveries,
                    _MAX_SEMANTIC_LOOP_RECOVERIES,
                )
                # The model still gets the result; the hint follows it. Skipping the
                # result here left the model guessing with only the hint (de5d0990).
                return False

        if diagnosis.health not in _AUTO_ABORT_HEALTH and not (
            diagnosis.health == TrajectoryHealth.SEMANTIC_LOOP
            and self._semantic_loop_recoveries >= _MAX_SEMANTIC_LOOP_RECOVERIES
        ):
            return False

        # Enrich the abort message with policy context when the trajectory degenerated
        # because of security blocks rather than true semantic repetition.
        security_context = ""
        if self._last_error_class in _POLICY_ERROR_CLASSES:
            count = self._error_class_streak.get(self._last_error_class, 0)
            security_context = (
                f" (underlying cause: {count}× consecutive '{self._last_error_class}' "
                f"errors — check security_validators.py allowlists)"
            )
        outcome.loop_error = (
            f"Trajectory {diagnosis.health.value} for step '{step.id}': "
            f"{diagnosis.detail}{security_context}. Auto-aborting step."
        )
        outcome.events.append(ErrorEvent(error=outcome.loop_error))
        outcome.abort_step = True
        return True

    def _denial_loop(self, step: Step, result: ToolResult, outcome: BatchOutcome) -> bool:
        """H18d: too many refused calls in a step, or in a session, and a person decides."""
        from weebot.application.services.tool_approval import DENIAL_DATA_KEY, denial_breaker

        if not (result.data or {}).get(DENIAL_DATA_KEY):
            return False
        tripped = denial_breaker().record(session_id_var.get() or "", step.id)
        if tripped is None:
            return False
        scope = "this step" if tripped == "step" else "this session"
        outcome.loop_error = (
            f"Step '{step.id}' stopped: too many tool calls were refused in {scope}."
        )
        outcome.events.append(ErrorEvent(error=outcome.loop_error))
        outcome.events.append(
            WaitForUserEvent(
                question=(
                    f"Too many tool calls were refused in {scope} (last: "
                    f"{(result.error or '')[:300]}).\n"
                    f"Step: {step.description!r}.\n\n"
                    "Please either:\n"
                    "  1. Rephrase the task to avoid the refused operation, or\n"
                    "  2. Change the approval settings if appropriate, then resume."
                )
            )
        )
        outcome.abort_step = True
        return True

    def _policy_error_loop(self, step: Step, result: ToolResult, outcome: BatchOutcome) -> bool:
        """Fix 5: the same policy error class three times running asks a human."""
        if not result.is_error:
            self._last_error_class = None
            self._error_class_streak.clear()
            return False

        if is_expected_failure(step.description or ""):
            # TDD RED phase — a non-zero exit is expected, not a loop.
            return False

        error_class = classify_tool_error(result.error or result.output or "")
        if not error_class:
            return False

        if error_class == self._last_error_class:
            self._error_class_streak[error_class] = self._error_class_streak.get(error_class, 0) + 1
        else:
            self._error_class_streak = {error_class: 1}
            self._last_error_class = error_class

        if self._error_class_streak.get(error_class, 0) < _MAX_SAME_ERROR_CLASS:
            return False

        outcome.loop_error = (
            f"Step '{step.id}' is stuck: the same error class '{error_class}' "
            f"has triggered {self._error_class_streak[error_class]} consecutive times. "
            f"Last error: {(result.error or result.output)[:300]}. "
            "Requesting user input to unblock."
        )
        outcome.events.append(ErrorEvent(error=outcome.loop_error))
        outcome.events.append(
            WaitForUserEvent(
                question=(
                    f"The agent is blocked by a '{error_class}' policy and cannot "
                    f"proceed with step: {step.description!r}.\n"
                    f"Last error: {(result.error or result.output)[:500]}\n\n"
                    "Please either:\n"
                    "  1. Rephrase the task to avoid the blocked operation, or\n"
                    "  2. Adjust security settings if appropriate, then resume."
                )
            )
        )
        outcome.abort_step = True
        return True

    async def _middleware(
        self, executor: ExecutorAgent, tool_name: str, event_args: dict, result: ToolResult
    ) -> ToolResult | None:
        """Apply `after_tool_call`; None means the batch must stop."""
        chain = executor._middleware_chain
        if chain is None or chain.is_empty():
            return result
        modified = await chain.apply_after_tool_call(
            tool_name=tool_name,
            arguments=event_args,
            output=result.output or "",
            error=result.error,
            is_error=result.is_error,
        )
        if modified.output != (result.output or ""):
            return _merge_middleware_result(result, modified)
        return result
