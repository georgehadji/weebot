"""Learning rate scheduler for SkillOpt — controls edit budget over steps.

The textual learning rate L_t (paper §3.4) limits how many edits are applied
per step.  Starts with larger budgets for coarse improvements and decays
toward smaller budgets for consolidation.
"""
from __future__ import annotations

import math


class LearningRateScheduler:
    """Textual learning rate (edit budget) scheduler.

    Supports constant, cosine, linear, and inverse schedules matching
    the SkillOpt paper's design space (Table 2e).
    """

    def __init__(
        self,
        initial: int = 8,
        floor: int = 2,
        schedule: str = "cosine",
    ):
        self.initial = initial
        self.floor = floor
        self.schedule = schedule

    def budget_for_step(self, step: int, total_steps: int) -> int:
        """Return the edit budget for a given step number.

        Args:
            step: Current step (0-indexed).
            total_steps: Total steps in the process.

        Returns:
            Integer edit budget >= floor.
        """
        if total_steps <= 0:
            return self.initial

        progress = step / total_steps
        progress = min(progress, 1.0)

        if self.schedule == "constant":
            return self.initial

        if self.schedule == "cosine":
            # Cosine decay: slow start, fast middle, slow end
            lr = self.floor + 0.5 * (self.initial - self.floor) * (
                1 + math.cos(math.pi * progress)
            )
            return max(self.floor, int(round(lr)))

        if self.schedule == "linear":
            lr = self.initial - (self.initial - self.floor) * progress
            return max(self.floor, int(round(lr)))

        if self.schedule == "inverse":
            # 1 / (1 + progress_factor * step)
            factor = (self.initial - self.floor) / max(self.floor, 1)
            lr = self.initial / (1 + factor * step)
            return max(self.floor, int(round(lr)))

        return self.initial

    def __repr__(self) -> str:
        return (
            f"LearningRateScheduler(initial={self.initial}, "
            f"floor={self.floor}, schedule='{self.schedule}')"
        )
