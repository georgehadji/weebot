"""Abstract base for all agent flows — cross-package interface.

Extracted from ``weebot/application/flows/base_flow.py`` to break the
circular dependency between ``services/`` and ``flows/``.
Services depend on this abstraction; flows implement it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Callable

from weebot.domain.models.event import AgentEvent


class BaseFlow(ABC):
    """Abstract base for all agent flows.

    Each flow implementation (PlanActFlow, ChatFlow, etc.) yields
    ``AgentEvent`` objects as it progresses through its state machine.
    """

    @abstractmethod
    async def run(self, prompt: str) -> AsyncGenerator[AgentEvent, None]:
        """Execute the flow for the given prompt, yielding events."""
        ...

    @abstractmethod
    def is_done(self) -> bool:
        """Return True if the flow has completed."""
        ...

    async def teardown(self) -> None:
        """Release resources held by the flow (e.g. tool service connections)."""
        ...


class FlowRegistry:
    """Registry of flow factories, keyed by flow type string.

    Replaces the switch/match in ``interfaces/factories.create_flow()``
    so that flow registration is explicit and dependency inversion is
    maintained.  Services that need to create flows (e.g., ``TaskRunner``)
    depend on this registry, not on concrete flow modules.
    """

    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., BaseFlow]] = {}

    def register(self, name: str, factory: Callable[..., BaseFlow]) -> None:
        """Register a flow factory under *name*.

        Args:
            name: Flow type identifier (e.g. ``"plan_act"``, ``"chat"``).
            factory: Callable that accepts keyword arguments and returns
                     a ``BaseFlow`` instance.
        """
        self._factories[name] = factory

    def create(self, name: str, **kwargs: object) -> BaseFlow:
        """Create a flow instance by type name.

        Args:
            name: Registered flow type name.
            **kwargs: Passed through to the factory.

        Returns:
            A ``BaseFlow`` instance.

        Raises:
            KeyError: If *name* is not registered.
        """
        factory = self._factories.get(name)
        if factory is None:
            available = ", ".join(self._factories.keys())
            raise KeyError(
                f"Unknown flow type: {name!r}. Available: {available}"
            )
        return factory(**kwargs)

    def list_types(self) -> list[str]:
        """Return all registered flow type names."""
        return list(self._factories.keys())
