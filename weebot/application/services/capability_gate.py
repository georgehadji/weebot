"""CapabilityGate — tier-based access control for skills and tools.

Enforces four tiers:
- PUBLIC:     Safe, no restrictions
- CONTROLLED: Requires user presence (interactive mode)
- RESTRICTED: Requires explicit user approval per usage
- PRIVILEGED: Requires operator override token
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from weebot.domain.models.capability_tier import (
    AnticipatorySimulationResult,
    CapabilityTier,
)

logger = logging.getLogger(__name__)


class CapabilityGate:
    """Gate that checks capability tiers before loading skills/tools.

    Provides deterministic tier enforcement without LLM calls.
    """

    def __init__(
        self,
        default_tier: CapabilityTier = CapabilityTier.PUBLIC,
        operator_token: Optional[str] = None,
    ) -> None:
        """Initialize the gate.

        Args:
            default_tier: Default tier for skills that don't declare one.
            operator_token: Optional override token for PRIVILEGED operations.
                            In production, this should come from env/config.
        """
        self._default_tier = default_tier
        self._operator_token = operator_token

    def check(
        self, tier: CapabilityTier, context: dict[str, Any]
    ) -> tuple[bool, str]:
        """Check whether the current context allows this tier.

        Deterministic check — no I/O, no LLM calls.

        Args:
            tier: The tier to check.
            context: Must contain:
                - 'user_present' (bool): Is the user in an interactive session?
                - 'session_mode' (str): 'interactive' | 'background' | 'scheduled'
                - 'operator_override' (str, optional): Operator token for privileged ops

        Returns:
            Tuple of (allowed, reason).
        """
        if tier == CapabilityTier.PUBLIC:
            return True, "Public skills are always allowed"

        if tier == CapabilityTier.CONTROLLED:
            user_present = context.get("user_present", False)
            session_mode = context.get("session_mode", "background")
            if user_present or session_mode == "interactive":
                return True, "Controlled skill allowed — user is present"
            return False, (
                "Controlled skill requires user presence. "
                "Run in interactive mode to use this skill."
            )

        if tier == CapabilityTier.RESTRICTED:
            user_present = context.get("user_present", False)
            has_approval = context.get("explicit_approval", False)
            if has_approval:
                return True, "Restricted skill allowed — explicit approval given"
            if user_present:
                return True, (
                    "Restricted skill allowed — user present, "
                    "will prompt for per-use approval at execution time"
                )
            return False, (
                "Restricted skill requires explicit user approval per use. "
                "Use --approve or run interactively."
            )

        if tier == CapabilityTier.PRIVILEGED:
            operator_token = context.get("operator_override", "")
            if operator_token and operator_token == self._operator_token:
                return True, "Privileged skill allowed — operator override accepted"
            return False, (
                "Privileged skill requires operator override token. "
                "Set OPERATOR_TOKEN or use --privileged flag."
            )

        return True, f"Unknown tier '{tier}' — defaulting to allowed"

    def simulate(
        self, skill_name: str, manifest: dict[str, Any]
    ) -> AnticipatorySimulationResult:
        """Preview consequences of executing a privileged skill.

        This is a lightweight simulation based on the manifest metadata
        (tool requirements, tier, permissions) — no actual execution.

        Args:
            skill_name: Name of the skill to simulate.
            manifest: The skill's manifest dictionary.

        Returns:
            Simulation result with predicted effects and risk level.
        """
        effects: list[str] = []
        risk_level = "low"

        # Check tools used by this skill
        requires = manifest.get("requires", [])
        tier = manifest.get("tier", "public")

        if "bash" in requires:
            effects.append("Executes shell commands on the host system")
            risk_level = "high"
        if "computer_use" in requires:
            effects.append("Controls screen and mouse input")
            risk_level = "high" if tier == "privileged" else "medium"
        if "file_editor" in requires:
            effects.append("Modifies files on disk")
            risk_level = "medium" if tier in ("restricted", "privileged") else "low"
        if "advanced_browser" in requires:
            effects.append("Navigates web pages and extracts content")
        if "web_search" in requires:
            effects.append("Searches the public web")

        anticipatory_simulation = manifest.get("anticipatory_simulation", False)
        if anticipatory_simulation and tier in ("restricted", "privileged"):
            effects.append(
                f"[SIMULATION] {manifest.get('name', skill_name)}: "
                f"Would execute {len(requires)} tools on your behalf"
            )

        return AnticipatorySimulationResult(
            skill_name=skill_name,
            expected_effects=effects,
            risk_level=risk_level,
            simulation_passed=risk_level != "high" or tier != "privileged",
        )

    def tier_from_manifest(self, manifest: dict) -> CapabilityTier:
        """Extract the tier from a skill manifest, falling back to default.

        Args:
            manifest: Skill manifest dictionary.

        Returns:
            Resolved CapabilityTier.
        """
        tier_str = manifest.get("tier", self._default_tier.value)
        try:
            return CapabilityTier(tier_str)
        except ValueError:
            logger.warning(
                "Unknown tier '%s' in manifest, defaulting to %s",
                tier_str, self._default_tier.value,
            )
            return self._default_tier
