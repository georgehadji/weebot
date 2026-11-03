"""Iteration guard — loop bounds, tool-call cap, and stuck detection for ExecutorAgent."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field

from weebot.application.agents.executor._loop_detectors import (
    CycleDetector,
    EmptyResponseBudget,
    GuardConfig,
    GuardVerdict,
    RepetitionGuard,
    WallClockWrapUp,
)

logger = logging.getLogger(__name__)

# Default limits
# 24, not 12: a step doing real work (read, edit, run, verify) routinely needs more than
# twelve rounds, and the old cap ended those steps with a summary before the work was
# finished — the literal "Step completed (budget cap)." came from that summary's fallback.
# MAX_EXECUTOR_STEPS (50) still bounds each step, and the loop guards below still catch
# repetition, so this raises room to work rather than removing a guard.
# The numbers live in GuardConfig (_loop_detectors.py); these names are what others import.
DEFAULT_MAX_TOOL_CALLS_PER_STEP = GuardConfig().max_tool_calls_per_step
_MAX_TOOL_CALLS_PER_STEP = DEFAULT_MAX_TOOL_CALLS_PER_STEP  # back-compat for older imports

# Conversation-buffer size needed for one step to run its full tool budget.
# The buffer is cleared per step, then holds: the anchoring context message
# (goal, plan summary, step description), plus an assistant message AND a
# tool-result message per tool call. At the previous hard-coded 15 the anchor
# fell out of the window after ~7 tool calls -- the model lost the step
# description while still executing that step -- and eviction from the left
# split assistant/tool pairs, which providers reject outright.
#
# The slack covers [RECOVERY] and budget-cap system messages, which are
# appended outside the per-tool-call pairing.
_CONTEXT_TURN_SLACK = 6
DEFAULT_MAX_CONTEXT_TURNS = 1 + (2 * DEFAULT_MAX_TOOL_CALLS_PER_STEP) + _CONTEXT_TURN_SLACK


@dataclass
class IterationGuardState:
    """Mutable state for a single step's execution loop.

    Reset at the start of each ``execute_step()`` call.
    """

    tool_call_count: int = 0
    repeated_assistant_turns: int = 0
    last_assistant_text: str = ""
    repeated_tool_calls: int = 0
    last_tool_signature: str | None = None
    recent_tool_signatures: deque = field(default_factory=lambda: deque(maxlen=6))
    tool_calls_attempted: int = 0
    tool_calls_succeeded: int = 0
    semantic_loop_recoveries: int = 0


class IterationGuard:
    """Encapsulates loop-bounds checking and stuck detection for a step.

    Usage::

        guard = IterationGuard(step_id, GuardConfig())
        while guard.should_continue():
            guard.record_loop_turn()
            # ... execute tool call ...
            guard.record_tool_call(tc_signature)
            if guard.is_stuck():
                guard.emit_stuck_warning()
                break

            if guard.is_tool_call_budget_exhausted():
                # Force summary, then break
                ...
                break
    """

    def __init__(self, step_id: str, config: GuardConfig | None = None):
        cfg = config or GuardConfig()
        self._step_id = step_id
        self._max_tool_calls = cfg.max_tool_calls_per_step
        self._max_repeated_assistant = cfg.max_repeated_assistant_turns
        self._repeated_tool_sig_limit = cfg.repeated_tool_signature_limit
        self.state = IterationGuardState()
        self._cycles = CycleDetector(cfg.cycle_periods)
        self._empty = EmptyResponseBudget(
            cfg.empty_max_retries, cfg.empty_cost_ratio, cfg.empty_cost_cap_usd
        )
        self._repetition = RepetitionGuard(cfg.repetition_threshold, cfg.repetition_window)
        self._wall_clock = WallClockWrapUp(cfg.wall_clock_budget_s, cfg.wrap_up_ratio)

    # ── Events ────────────────────────────────────────────────────

    def record_loop_turn(self) -> None:
        """Count one pass of the step's loop; the cap compares it with the tool-call limit."""
        self.state.tool_call_count += 1

    def record_assistant_turn(self, normalized_text: str) -> None:
        """Track repeated assistant-only responses (no tool calls)."""
        if normalized_text and normalized_text == self.state.last_assistant_text:
            self.state.repeated_assistant_turns += 1
        else:
            self.state.repeated_assistant_turns = 0
        self.state.last_assistant_text = normalized_text

    def record_tool_call(self, signature: str) -> GuardVerdict | None:
        """Track tool-call signature for repeated-signature detection; report a cycle."""
        self.state.recent_tool_signatures.append(signature)
        if signature and signature == self.state.last_tool_signature:
            self.state.repeated_tool_calls += 1
        else:
            self.state.repeated_tool_calls = 0
        self.state.last_tool_signature = signature
        return self._cycles.observe(signature)

    def observe_assistant_text(self, text: str) -> list[str]:
        """Notes for the model when this turn's text repeats the last turns' (H11)."""
        verdict = self._repetition.observe(text or "")
        return [verdict.message] if verdict else []

    def observe_empty_reply(self, turn_cost: float, step_cost: float) -> GuardVerdict:
        """RETRY while the wasted spend stays small, otherwise STOP (H11)."""
        return self._empty.observe(turn_cost, step_cost)

    def wrap_up_note(self) -> str | None:
        """The one note asking the model to finish, once the step's time is mostly used."""
        return self._wall_clock.observe()

    # ── Queries ───────────────────────────────────────────────────

    def is_tool_call_budget_exhausted(self) -> bool:
        """Return True if tool-call cap for this step is exceeded."""
        return self.state.tool_call_count > self._max_tool_calls

    def is_assistant_turn_loop(self) -> bool:
        """Return True if the LLM is repeating the same assistant text."""
        return self.state.repeated_assistant_turns >= self._max_repeated_assistant

    def is_tool_signature_loop(self) -> bool:
        """Return True if the same tool signature repeats."""
        return self.state.repeated_tool_calls >= self._repeated_tool_sig_limit

    def is_tool_call_repeating(self, signature: str) -> bool:
        """Return True if *signature* appears too many times recently."""
        count = sum(1 for s in self.state.recent_tool_signatures if s == signature)
        return count >= self._repeated_tool_sig_limit

    def build_stuck_error(self, reason: str, step_description: str) -> str:
        """Build a descriptive stuck-error message."""
        recent = list(self.state.recent_tool_signatures)
        return (
            f"Step stuck: {reason}. "
            f"Recent tool signatures: {recent}. "
            f"Step: {step_description}"
        )
