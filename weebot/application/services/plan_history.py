"""Plan history — undo/redo stack management for plan operations.

Extracted from PlanActFlow to isolate the snapshot/undo/redo concern
into its own service with a single responsibility.
"""
from __future__ import annotations

from typing import Optional, TypeVar

TPlan = TypeVar("TPlan")


class PlanHistory:
    """Manages undo/redo history for plan state snapshots.

    Each snapshot pushes the current plan onto the undo stack.
    Undo/redo operations move plans between the two stacks,
    and any new snapshot after an undo clears the redo stack
    (standard undo/redo semantics).

    Usage:
        history = PlanHistory()
        history.snapshot(plan)      # Save current state
        prev = history.undo(plan)   # Go back one step
        next = history.redo(plan)   # Go forward one step
    """

    def __init__(self) -> None:
        self._undo_stack: list[TPlan] = []
        self._redo_stack: list[TPlan] = []

    def snapshot(self, plan: TPlan) -> None:
        """Push current plan onto undo stack and clear redo history.

        Args:
            plan: The current plan state to snapshot.
        """
        if plan is not None:
            self._undo_stack.append(plan)
            self._redo_stack.clear()

    def undo(self, current_plan: TPlan) -> Optional[TPlan]:
        """Revert to the previous plan state if available.

        The current plan is pushed onto the redo stack so the undo
        can be reversed.

        Args:
            current_plan: The current plan (pushed onto redo stack).

        Returns:
            The previous plan, or None if undo stack is empty.
        """
        if not self._undo_stack:
            return None
        if current_plan is not None:
            self._redo_stack.append(current_plan)
        return self._undo_stack.pop()

    def redo(self, current_plan: TPlan) -> Optional[TPlan]:
        """Re-apply a plan state that was previously undone.

        The current plan is pushed onto the undo stack.

        Args:
            current_plan: The current plan (pushed onto undo stack).

        Returns:
            The next plan, or None if redo stack is empty.
        """
        if not self._redo_stack:
            return None
        if current_plan is not None:
            self._undo_stack.append(current_plan)
        return self._redo_stack.pop()

    def get_all(self) -> list[TPlan]:
        """Return all plans in the undo stack (historical snapshots)."""
        return list(self._undo_stack)

    @property
    def can_undo(self) -> bool:
        """Whether an undo operation is available."""
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        """Whether a redo operation is available."""
        return len(self._redo_stack) > 0

    @property
    def undo_count(self) -> int:
        """Number of snapshots in the undo stack."""
        return len(self._undo_stack)

    @property
    def redo_count(self) -> int:
        """Number of snapshots in the redo stack."""
        return len(self._redo_stack)

    def clear(self) -> None:
        """Clear both undo and redo stacks."""
        self._undo_stack.clear()
        self._redo_stack.clear()

    # ── Diversification (Hallmark-inspired) ─────────────────────────

    @staticmethod
    def plan_fingerprint(plan: TPlan) -> str:
        """Return a hash of the plan's structural fingerprint.

        Captures: step count and tool sequence pattern (which tools
        appear in which order). Does NOT capture content — two plans
        with different content but the same structure produce the
        same fingerprint.
        """
        import hashlib
        import re

        steps = getattr(plan, "steps", [])
        if not steps:
            return "empty"

        # Infer likely tools from step descriptions
        tool_keywords = {
            "bash": r"\b(bash|powershell|shell|command|terminal|run|execute)\b",
            "web_search": r"\b(search|find|lookup|research|browse|google)\b",
            "file_editor": r"\b(file|edit|write|read|open|create|delete|rename|move|copy)\b",
            "python_execute": r"\b(python|script|code|analyze|process|compute)\b",
        }

        parts = [str(len(steps))]
        for step in steps:
            desc = getattr(step, "description", "") or ""
            tools = [t for t, pat in tool_keywords.items() if re.search(pat, desc, re.I)]
            parts.append("+".join(tools) if tools else "unknown")

        return hashlib.sha256(":".join(parts).encode()).hexdigest()[:8]

    def is_too_similar(
        self,
        new_plan: TPlan,
        threshold: float = 0.7,
        window: int = 3,
    ) -> bool:
        """Check if *new_plan* is too similar to recent plans.

        Compares the fingerprint of *new_plan* against the last *window*
        plans in the undo stack.  Two plans are similar if they share
        the same fingerprint.

        Args:
            new_plan: The newly generated plan to check.
            threshold: Similarity threshold (0-1).  Currently binary:
                       same fingerprint = 1.0, different = 0.0.
            window: Number of recent plans to compare against.

        Returns:
            True if the plan is too similar to any recent plan.
        """
        new_fp = self.plan_fingerprint(new_plan)
        recent = self._undo_stack[-window:] if len(self._undo_stack) >= window else self._undo_stack

        for old_plan in recent:
            old_fp = self.plan_fingerprint(old_plan)
            if old_fp == new_fp:
                return True

        return False
