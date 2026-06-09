"""RoleModelSelector — assigns model IDs to functional agent roles.

Reads from ROLE_MODEL_CONFIG in model_cascade_config.  Falls back to the
flow's default model if the role is not configured or all role models are
unavailable (circuit open).

This is a pure application-layer service: no LLM calls, no I/O.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RoleModelSelector:
    """Returns the preferred model ID for a given agent role.

    Args:
        default_model: Fallback model ID when role config is absent.
    """

    def __init__(self, default_model: Optional[str] = None) -> None:
        self._default = default_model

    def select(self, role: str) -> str:
        """Return the primary model ID for *role*.

        Falls back to *default_model* if the role is not in ROLE_MODEL_CONFIG.
        """
        from weebot.core.model_cascade_config import ROLE_MODEL_CONFIG
        models = ROLE_MODEL_CONFIG.get(role, [])
        if models:
            return models[0]
        if self._default:
            return self._default
        raise ValueError(
            f"No model configured for role '{role}' and no default set"
        )

    def fallback_chain(self, role: str) -> list[str]:
        """Return the full ordered fallback list for *role*."""
        from weebot.core.model_cascade_config import ROLE_MODEL_CONFIG
        return list(
            ROLE_MODEL_CONFIG.get(
                role,
                [self._default] if self._default else [],
            )
        )
