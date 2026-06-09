from __future__ import annotations

"""[DEPRECATED] No adapter implementation exists.
Tracked in docs/plans/ARCHITECTURE_9_PLAN.md.

Capability gate port — abstract interface for tier-based access control.
"""

from abc import ABC, abstractmethod
from typing import Any

from weebot.domain.models.capability_tier import (
    AnticipatorySimulationResult,
    CapabilityTier,
)


class CapabilityGatePort(ABC):
    """Interface for capability-tier access control.

    Every skill/tool goes through this gate before being loaded.
    """

    @abstractmethod
    async def check(
        self, tier: CapabilityTier, context: dict[str, Any]
    ) -> tuple[bool, str]:
        """Check whether the current context allows this tier.

        Args:
            tier: The tier to check.
            context: Execution context (user presence, session mode, etc.).

        Returns:
            Tuple of (allowed, reason). If allowed is False, reason explains why.
        """
        ...

    @abstractmethod
    async def simulate(
        self, skill_name: str, manifest: dict[str, Any]
    ) -> AnticipatorySimulationResult:
        """Preview consequences of executing a privileged skill.

        Args:
            skill_name: Name of the skill to simulate.
            manifest: The skill's manifest dictionary.

        Returns:
            Simulation result with predicted effects and risk level.
        """
        ...
