"""Feature flags for weebot — gating experimental or high-risk capabilities.

Each flag defaults to OFF.  Flags should be toggled via environment variables
or a config file, never hardcoded to True in production.

HyperAgents Enhancement 7: METACOGNITIVE_IMPROVEMENT_ENABLED controls whether
the SelfImprover can edit its own prompt and allowlist (self-referential
improvement).  Default OFF — requires explicit opt-in.
"""
from __future__ import annotations

import os
from typing import Any, Callable


def _env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean feature flag from an environment variable.

    Accepts '1', 'true', 'yes', 'on' (case-insensitive) as True.
    """
    val = os.environ.get(name, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


# ── HyperAgents Enhancement 7 ───────────────────────────────────────────────
# When True, the SelfImprover can modify its own prompt and configuration.
# This enables metacognitive self-improvement but carries operational risk:
# a bad self-modification could degrade the improvement pipeline itself.
# Always review meta-edits in MetaImprovementLog after enabling.
METACOGNITIVE_IMPROVEMENT_ENABLED: bool = _env_bool(
    "WEEBOT_METACOGNITIVE_IMPROVEMENT", default=False
)


def is_enabled(flag_name: str) -> bool:
    """Check if a feature flag is enabled by name."""
    return globals().get(flag_name, False)


def require(flag_name: str) -> None:
    """Raise RuntimeError if *flag_name* is not enabled."""
    if not is_enabled(flag_name):
        raise RuntimeError(
            f"Feature flag '{flag_name}' is disabled. "
            "Set the corresponding environment variable to enable it."
        )
