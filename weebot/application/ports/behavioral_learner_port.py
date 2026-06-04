"""Behavioral Learner port — abstract interface for automatic rule extraction."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from weebot.domain.models.behavioral_rule import BehavioralRule


class BehavioralLearnerPort(ABC):
    """Interface for automatic behavioral rule extraction.

    Monitors user correction patterns and extracts persistent rules
    injected into every future executor prompt.
    """

    @abstractmethod
    async def learn_from_correction(
        self, user_message: str, context: dict[str, Any]
    ) -> Optional[BehavioralRule]:
        """Extract a behavioral rule from a user correction, if one exists.

        Args:
            user_message: The user's message text.
            context: Dict with session context, current step, and tool calls.

        Returns:
            A BehavioralRule if the message contains a correction, None otherwise.
        """
        ...

    @abstractmethod
    async def get_active_rules(self) -> list[BehavioralRule]:
        """Get all active behavioral rules.

        Returns:
            List of BehavioralRule instances, ordered by most recently applied first.
        """
        ...

    @abstractmethod
    async def record_application(self, rule: BehavioralRule) -> None:
        """Record that a rule was injected into a system prompt.

        Args:
            rule: The rule that was applied.
        """
        ...
