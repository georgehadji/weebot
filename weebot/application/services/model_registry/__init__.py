"""Model registry — decomposed from the god module ``model_selection.py``.

Modules in this package:
- ``_models.py`` — ``ModelTier`` enum, ``ModelConfig`` dataclass
- ``_catalog.py`` — ``MODELS`` dict (327 unique LLM configurations)
- ``_strategies.py`` — ``ModelSelectionStrategy`` ABC + 3 implementations
- ``_service.py`` — ``ModelSelectionService`` (strategy-based routing)
"""
from weebot.application.services.model_registry._models import ModelConfig, ModelTier
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
