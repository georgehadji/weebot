"""Agent-to-Agent (A2A) Protocol — capability-based agent discovery and delegation.

Part of Enhancement 3 from the Agentic AI plan.  Defines ``AgentCard``
(agent metadata manifest) and ``AgentRegistry`` (local directory of
available agents and their capabilities).

Usage:
    registry = AgentRegistry()
    registry.register(AgentCard(
        name="code_agent",
        capabilities=["code_generation", "debugging", "code_review"],
        version="1.0",
    ))
    registry.register(AgentCard(
        name="research_agent",
        capabilities=["web_search", "document_analysis", "fact_checking"],
        version="1.0",
    ))

    # Find an agent with a specific capability
    code_agents = registry.find_by_capability("code_generation")
    # → [AgentCard(name="code_agent", ...)]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentCard:
    """Agent metadata manifest for the A2A registry.

    Attributes:
        name: Unique identifier for this agent.
        capabilities: List of capability strings this agent provides.
        version: Semantic version string.
        description: Human-readable description of the agent's role.
        endpoint: How to reach this agent (module path or function ref).
    """
    name: str
    capabilities: list[str]
    version: str = "1.0"
    description: str = ""
    endpoint: str = ""


class AgentRegistry:
    """Local directory of agent cards.

    Supports registration, lookup by name, and capability-based discovery.

    Usage:
        registry = AgentRegistry()
        registry.register(AgentCard(name="code", capabilities=["code"]))
        agent = registry.get("code")
        agents = registry.find_by_capability("code")
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentCard] = {}

    def register(self, card: AgentCard) -> None:
        """Register an agent card (replaces existing with same name)."""
        self._agents[card.name] = card

    def get(self, name: str) -> Optional[AgentCard]:
        """Look up an agent by name."""
        return self._agents.get(name)

    def find_by_capability(self, capability: str) -> list[AgentCard]:
        """Find all agents that provide a given capability."""
        return [
            card for card in self._agents.values()
            if capability in card.capabilities
        ]

    def list_all(self) -> list[AgentCard]:
        """Return all registered agents."""
        return list(self._agents.values())

    def remove(self, name: str) -> None:
        """Remove an agent from the registry."""
        self._agents.pop(name, None)

    def __len__(self) -> int:
        return len(self._agents)
