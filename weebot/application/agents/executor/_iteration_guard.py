"""Iteration guard — loop bounds, tool-call cap, and stuck detection for ExecutorAgent."""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Default limits
_MAX_TOOL_CALLS_PER_STEP = 12
_MAX_REPEATED_ASSISTANT_TURNS = 2
_REPEATED_TOOL_SIGNATURE_LIMIT = 4

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
DEFAULT_MAX_CONTEXT_TURNS = 1 + (2 * _MAX_TOOL_CALLS_PER_STEP) + _CONTEXT_TURN_SLACK


@dataclass
class IterationGuardState:
    """Mutable state for a single step's execution loop.

    Reset at the start of each ``execute_step()`` call.
    """
    tool_call_count: int = 0
    repeated_assistant_turns: int = 0
    last_assistant_text: str = ""
    repeated_tool_calls: int = 0
    last_tool_signature: Optional[str] = None
    recent_tool_signatures: deque = field(default_factory=lambda: deque(maxlen=6))
    tool_calls_attempted: int = 0
    tool_calls_succeeded: int = 0
    semantic_loop_recoveries: int = 0


class IterationGuard:
    """Encapsulates loop-bounds checking and stuck detection for a step.

    Usage::

        guard = IterationGuard(step_budget=step_budget)
        while guard.should_continue():
            guard.record_iteration()
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

    def __init__(
        self,
        step_id: str,
        max_tool_calls_per_step: int = _MAX_TOOL_CALLS_PER_STEP,
        max_repeated_assistant_turns: int = _MAX_REPEATED_ASSISTANT_TURNS,
        repeated_tool_signature_limit: int = _REPEATED_TOOL_SIGNATURE_LIMIT,
    ):
        self._step_id = step_id
        self._max_tool_calls = max_tool_calls_per_step
        self._max_repeated_assistant = max_repeated_assistant_turns
        self._repeated_tool_sig_limit = repeated_tool_signature_limit
        self.state = IterationGuardState()

    # ── Events ────────────────────────────────────────────────────

    def record_iteration(self) -> None:
        """Increment tool-call counter; call once per while-loop body."""
        self.state.tool_call_count += 1

    def record_assistant_turn(self, normalized_text: str) -> None:
        """Track repeated assistant-only responses (no tool calls)."""
        if normalized_text and normalized_text == self.state.last_assistant_text:
            self.state.repeated_assistant_turns += 1
        else:
            self.state.repeated_assistant_turns = 0
        self.state.last_assistant_text = normalized_text

    def record_tool_call(self, signature: str) -> None:
        """Track tool-call signature for repeated-signature detection."""
        self.state.recent_tool_signatures.append(signature)
        if signature and signature == self.state.last_tool_signature:
            self.state.repeated_tool_calls += 1
        else:
            self.state.repeated_tool_calls = 0
        self.state.last_tool_signature = signature

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
