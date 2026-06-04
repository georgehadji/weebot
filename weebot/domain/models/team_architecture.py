"""Team architecture domain models for harness generation (H3).

These models describe an agent team design: which agents exist,
what patterns they follow, and what skills they use.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TeamPattern(Enum):
    """Six team architecture patterns from revfactory/harness."""
    PIPELINE = "pipeline"
    FAN_OUT_FAN_IN = "fan_out_fan_in"
    EXPERT_POOL = "expert_pool"
    PRODUCER_REVIEWER = "producer_reviewer"
    SUPERVISOR = "supervisor"
    HIERARCHICAL_DELEGATION = "hierarchical_delegation"


@dataclass
class AgentDefinition:
    """An agent to be generated in the harness."""
    name: str
    role: str
    persona: str = ""
    skills: list[str] = field(default_factory=list)
    agent_type: str = "general-purpose"  # general-purpose, Explore, Plan, or custom
    model: str = "opus"


@dataclass
class SkillBlueprint:
    """A skill to be generated for the harness."""
    name: str
    description: str
    content: str = ""
    references: list[str] = field(default_factory=list)


@dataclass
class TeamArchitecture:
    """Complete team architecture design from harness generation."""
    domain: str
    pattern: TeamPattern
    agents: list[AgentDefinition] = field(default_factory=list)
    skills: list[SkillBlueprint] = field(default_factory=list)
    orchestrator_description: str = ""
    rationale: str = ""
