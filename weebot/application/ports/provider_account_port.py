"""ProviderAccountPort — account-level queries against the LLM gateway.

Not completions: those go through LLMPort. This is what the cascade asks the
gateway *about* itself -- how much credit is left, which models exist right
now. CascadeExecutor used to make both calls as raw httpx requests to
openrouter.ai from inside the application layer (phase 3.1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelListing:
    """One model the gateway currently serves."""

    id: str
    context_length: int
    supports_tools: bool


class ProviderAccountPort(ABC):
    @abstractmethod
    async def remaining_credits(self) -> int | None:
        """Remaining credit, or None when it cannot be determined.

        None means "unknown", never "zero": a caller that filters models on a
        low balance must not strip them on a network blip.
        """

    @abstractmethod
    async def list_models(self) -> list[ModelListing]:
        """Every model the gateway serves now. Raises if the list is unreachable."""
