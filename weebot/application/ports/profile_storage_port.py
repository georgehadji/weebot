"""Profile storage port — abstract interface for user profile persistence.

Extracted from the original domain/models/user_profile.py monolith as
part of architecture remediation (step-6).  Adapt the port to different
backends via the composition root.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from weebot.domain.models.user_profile import UserProfile


class ProfileStoragePort(ABC):
    """Abstract interface for persisting user profiles."""

    @abstractmethod
    async def save_profile(self, profile: UserProfile) -> bool:
        """Persist a user profile."""
        ...

    @abstractmethod
    async def load_profile(self, user_id: str) -> Optional[UserProfile]:
        """Load a user profile by user ID."""
        ...

    @abstractmethod
    async def delete_profile(self, user_id: str) -> bool:
        """Remove a user profile."""
        ...

    @abstractmethod
    async def update_profile(self, profile: UserProfile) -> bool:
        """Update an existing user profile."""
        ...
