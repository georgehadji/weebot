"""SoulProviderPort — abstract interface for loading SOUL.md agent identities.

Decouples SOUL.md file loading from the PersonalityManager so the storage
backend (filesystem, database, remote) can be swapped without touching
core personality logic.

Moved from ``weebot.application.ports.soul_provider_port`` to
``weebot.core.soul_provider_port`` because ``core.personality_manager``
needs it (core must not depend on application layer).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.soul import SoulProfile


class SoulProviderPort(ABC):
    """Abstract interface for loading and seeding SOUL.md identity files."""

    @abstractmethod
    async def load(self, profile_name: str | None = None) -> SoulProfile | None:
        """Load a SOUL.md profile.

        Args:
            profile_name: Profile subdirectory name (e.g. ``"coder"``, ``"reviewer"``).
                          When ``None``, loads the default project-root SOUL.md.

        Returns:
            ``SoulProfile`` if a SOUL.md file was found and read, or ``None``
            if no file exists and auto-seeding is disabled.
        """
        ...

    @abstractmethod
    async def list_profiles(self) -> list[str]:
        """Return names of all profiles that have a SOUL.md file."""
        ...

    @abstractmethod
    async def seed(self, profile_name: str | None = None) -> SoulProfile:
        """Create a SOUL.md file from the default template.

        Args:
            profile_name: Profile to seed. ``None`` seeds the default profile.

        Returns:
            The newly created ``SoulProfile``.

        Raises:
            FileExistsError: If a SOUL.md file already exists for this profile.
        """
        ...
