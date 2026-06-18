"""Model selection service — re-export shim.

.. deprecated::
    Import from ``weebot.application.services.model_registry`` instead.
    This module will be removed in a future version.
"""
from __future__ import annotations

from weebot.application.services.model_registry import (  # noqa: F401
    CostOptimized,
    Fastest,
    ModelConfig,
    ModelSelectionService,
    ModelSelectionStrategy,
    ModelTier,
    QualityOptimized,
)
from weebot.application.services.model_registry._service import ModelSelectionService  # noqa: F401
from weebot.domain.models.task_type import TaskType       # noqa: F401  # backward compat
