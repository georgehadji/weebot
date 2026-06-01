"""StepBudget — thread-safe per-agent step allocation with consume/refund semantics.

Inspired by hermes-agent's IterationBudget pattern. Each ExecutorAgent instance
gets its own StepBudget. Parent agents default to MAX_EXECUTOR_STEPS (25);
sub-agents spawned by DispatchAgentsTool get SUBAGENT_MAX_STEPS (15).

The refund() method allows programmatic/internal tool calls to return their
step back to the budget so they don't eat into the agent's effective budget.
"""
from __future__ import annotations

import threading

__all__ = ["StepBudget"]


class StepBudget:
    """Thread-safe step budget with consume/refund semantics.

    Example::

        budget = StepBudget(max_steps=25)
        while budget.consume():
            # do one step of work
            if early_exit:
                budget.refund(budget.remaining)
                break
    """

    def __init__(self, max_steps: int) -> None:
        if max_steps < 1:
            raise ValueError(f"max_steps must be >= 1, got {max_steps}")
        self._max_steps = max_steps
        self._used: int = 0
        self._lock = threading.Lock()

    def consume(self) -> bool:
        """Atomically consume one step.

        Returns:
            True if the step was granted (budget not yet exhausted).
            False if the budget is already at maximum.
        """
        with self._lock:
            if self._used >= self._max_steps:
                return False
            self._used += 1
            return True

    def refund(self, count: int = 1) -> None:
        """Return *count* steps to the budget.

        Silently clamps to zero — cannot go negative. Safe to call
        multiple times (idempotent when count == 0).
        """
        if count < 1:
            return
        with self._lock:
            self._used = max(0, self._used - count)

    def reset(self) -> None:
        """Reset used count to zero (called between plan steps)."""
        with self._lock:
            self._used = 0

    @property
    def used(self) -> int:
        """Steps consumed so far."""
        with self._lock:
            return self._used

    @property
    def remaining(self) -> int:
        """Steps remaining in budget."""
        with self._lock:
            return max(0, self._max_steps - self._used)

    @property
    def exhausted(self) -> bool:
        """True when no steps remain."""
        return self.remaining == 0

    @property
    def max_steps(self) -> int:
        """Maximum step budget for this instance."""
        return self._max_steps

    def __repr__(self) -> str:
        return f"StepBudget(used={self.used}/{self._max_steps})"
