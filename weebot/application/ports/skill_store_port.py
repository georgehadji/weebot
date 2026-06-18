"""SkillStorePort — abstract port for persisting Skill models.

Application layer defines the contract, infrastructure layer provides
the SQLite adapter (SkillStore).  This enables flows and CQRS handlers
to depend on the port, not the concrete implementation.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from weebot.domain.models.skill import Skill


class SkillStorePort(ABC):
    """Persistence port for Skill models with version history."""

    @abstractmethod
    async def save(self, skill: Skill) -> None:
        """Persist a skill, creating or replacing it by name."""

    @abstractmethod
    async def load(self, name: str) -> Optional[Skill]:
        """Load a skill by name.  Returns None if not found."""

    @abstractmethod
    async def list_names(self) -> list[str]:
        """Return all stored skill names."""

    @abstractmethod
    async def delete(self, name: str) -> bool:
        """Delete a skill by name.  Returns True if it existed."""

    @abstractmethod
    async def export_best_md(self, name: str, output_path: str) -> None:
        """Write the best-validated skill content to a markdown file."""
