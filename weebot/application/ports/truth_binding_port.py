"""Truth-binding port — abstract interface for response-layer guards."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from weebot.domain.models.truth_binding import TruthBindingResult


class TruthBindingPort(ABC):
    """Interface for the truth-binding response validator.

    Implementations apply deterministic checks to agent responses
    before they reach the user. No LLM calls in the policy path.
    """

    @abstractmethod
    async def bind(self, response: str, context: dict[str, Any]) -> TruthBindingResult:
        """Validate a response, returning binding result.

        Args:
            response: The agent's text response to validate.
            context: Execution context including session events, current step,
                     tool call history, and any facts extracted so far.

        Returns:
            TruthBindingResult with passed/flags/violations and potentially
            rewritten bound_text.
        """
        ...
