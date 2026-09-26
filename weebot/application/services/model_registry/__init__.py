"""Model registry — decomposed from the god module ``model_selection.py``.

Modules in this package:
- ``_strategies.py`` — ``ModelSelectionStrategy`` ABC + 3 implementations
- ``_service.py`` — ``ModelSelectionService`` (strategy-based routing)

The data it routes over lives elsewhere: ``ModelConfig`` / ``ModelTier`` in
``weebot.domain.models.model_config`` and the generated ``MODELS`` catalog in
``weebot.config.model_catalog``, where infrastructure may read it too.
"""

from weebot.domain.models.model_config import ModelConfig, ModelTier
from weebot.application.services.model_registry._service import ModelSelectionService
from weebot.application.services.model_registry._strategies import (
    CostOptimized,
    Fastest,
    ModelSelectionStrategy,
    QualityOptimized,
)

__all__ = [
    "ModelConfig",
    "ModelTier",
    "ModelSelectionService",
    "ModelSelectionStrategy",
    "CostOptimized",
    "QualityOptimized",
    "Fastest",
]
