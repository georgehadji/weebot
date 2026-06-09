"""Compatibility shim for legacy agent_core_v2.py.

The original ``weebot.ai_router`` module was removed during the
infrastructure reorganisation (moved to ``rtk_ai_router.py``).
This stub re-exports the symbols that ``agent_core_v2.py`` needs
so that existing tests and legacy code paths continue to function
until ``agent_core_v2.py`` is fully retired.

Target sunset: 2027-03-01 (per agent_core_v2.py header).
"""
from __future__ import annotations

import warnings

from weebot.domain.models.task_type import TaskType  # re-export

warnings.warn(
    "weebot.ai_router is deprecated. "
    "Import ModelRouter / TaskType from their canonical locations instead.",
    DeprecationWarning,
    stacklevel=2,
)


class ModelRouter:
    """Legacy model router stub.

    Provides the minimal API surface that ``agent_core_v2.WeebotAgent``
    expects.  All methods are no-ops returning sensible defaults since
    the actual routing logic now lives in ``ExecutorAgent._call_with_cascade``
    and the OpenRouter adapter layer.
    """

    def __init__(self, daily_budget: float = 10.0) -> None:
        self.daily_budget = daily_budget
        self.cost_tracker = _CostTracker()

    def select_model(self, task_type: TaskType, budget_constraint: float | None = None) -> str:
        """Return a fallback model name.  The real cascade is in ExecutorAgent."""
        return "deepseek/deepseek-r1"

    async def generate_with_fallback(
        self,
        prompt: str,
        task_type: TaskType,
        use_cache: bool = True,
    ) -> dict:
        """No-op generator — agent_core_v2 is frozen, no real LLM calls."""
        return {"content": "", "model": "deepseek/deepseek-r1", "cost": 0.0}


class _CostTracker:
    """Minimal cost tracker stub for legacy compatibility."""

    def get_stats(self) -> dict:
        return {"today": 0.0, "total": 0.0, "tokens": 0}
