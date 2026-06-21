"""HarnessProfileResolver — resolves a role name to its Harness/RoleProfile.

Reads from ROLE_MODEL_CONFIG (simple list format, legacy) and optional
extended RoleProfile definitions. Falls back to existing config for
backward compatibility.
"""
from __future__ import annotations

import logging
from typing import Optional

from weebot.domain.models.role_profile import RoleProfile

logger = logging.getLogger(__name__)

# Extended profiles: when a role needs more than just a model list.
# Keys that exist here take priority over ROLE_MODEL_CONFIG.
# For most roles, ROLE_MODEL_CONFIG (the simple list) suffices.
_EXTENDED_PROFILES: dict[str, RoleProfile] = {}


def resolve_profile(role: str) -> RoleProfile:
    """Return the RoleProfile for *role*, falling back to ROLE_MODEL_CONFIG.

    First checks _EXTENDED_PROFILES, then ROLE_MODEL_CONFIG (simple list).
    Returns an empty profile if neither has the role.
    """
    from weebot.config.model_refs import ROLE_MODEL_CONFIG

    # Check extended profiles first
    profile = _EXTENDED_PROFILES.get(role)
    if profile is not None:
        return profile

    # Fall back to simple list from cascade config
    models = ROLE_MODEL_CONFIG.get(role, [])
    return RoleProfile(models=list(models))


def register_profile(role: str, profile: RoleProfile) -> None:
    """Register an extended RoleProfile for *role*."""
    _EXTENDED_PROFILES[role] = profile
    logger.info("Registered harness profile for role '%s': %s models, %d excluded tools",
                role, len(profile.models), len(profile.excluded_tools))


def get_tools_for_role(role: str, default_tools: list[str]) -> list[str]:
    """Return the effective tool list for *role*.

    Applies tools_override and excluded_tools from the role's profile.
    """
    profile = resolve_profile(role)
    if profile.tools_override is not None:
        tools = list(profile.tools_override)
    else:
        tools = list(default_tools)

    for excluded in profile.excluded_tools:
        if excluded in tools:
            tools.remove(excluded)

    return tools
