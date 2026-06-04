"""Capability tier domain model — permission levels for skills/tools.

Four tiers map to increasing restriction:
- PUBLIC:     Safe, no restrictions — always loaded
- CONTROLLED: Requires user presence (interactive mode)
- RESTRICTED: Requires explicit user approval per usage
- PRIVILEGED: Requires operator override token
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CapabilityTier(str, Enum):
    """Permission level for a skill or tool."""
    PUBLIC = "public"
    CONTROLLED = "controlled"
    RESTRICTED = "restricted"
    PRIVILEGED = "privileged"


class AnticipatorySimulationResult(BaseModel):
    """Result of previewing a privileged operation before execution."""
    skill_name: str = Field(description="The skill being simulated")
    expected_effects: list[str] = Field(
        default_factory=list,
        description="Predicted side effects of executing this skill",
    )
    risk_level: str = Field(
        default="low",
        description="'low' | 'medium' | 'high' — estimated risk",
    )
    simulation_passed: bool = Field(
        default=True,
        description="True if the simulation found no blocking issues",
    )
