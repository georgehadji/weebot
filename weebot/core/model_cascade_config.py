"""Cost estimate and context-size model switch, over the catalog and model_refs.

This module owns no model facts any more (W6.1, F18-F20). It used to keep a
second ``ModelConfig`` dataclass with hand-copied per-task prices, which
``estimate_cost`` fell back to and which had drifted from the catalog. Now:

* prices come from the generated OpenRouter catalog
  (``weebot.config.model_registry.get_model_config``);
* which model serves a task comes from ``model_refs.TASK_MODEL_CASCADE``.

Readers: ``CascadeExecutor`` (``estimate_cost``) and ``ContextSwitcher``
(``select_model_by_tokens``).
"""

from __future__ import annotations

import logging

from weebot.config.model_refs import TASK_MODEL_CASCADE

logger = logging.getLogger(__name__)

# At or above this many estimated tokens, the long-context cascade wins.
LONG_CONTEXT_TOKENS = 50_000


def select_model_by_tokens(task_type: str, estimated_tokens: int) -> str:
    """The first model of the task's cascade, or of ``long_context`` past the threshold."""
    if estimated_tokens >= LONG_CONTEXT_TOKENS:
        return TASK_MODEL_CASCADE["long_context"][0]
    return TASK_MODEL_CASCADE.get(task_type, TASK_MODEL_CASCADE["coding"])[0]


_UNPRICED_LOGGED: set[str] = set()


def estimate_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Cost in USD from the catalog's split prompt/completion rates.

    A model the catalog does not list costs 0.0 here and is logged: a guessed
    price is indistinguishable from a real one at the call site.
    """
    from weebot.config.model_registry import get_model_config

    config = get_model_config(model_id)
    if config is None:
        if model_id not in _UNPRICED_LOGGED:  # once per id: a hot path would flood the log
            _UNPRICED_LOGGED.add(model_id)
            logger.warning("estimate_cost: %r is not in the model catalog; costing 0.0", model_id)
        return 0.0
    return config.estimate_cost(prompt_tokens, completion_tokens)
