"""SkillIndexPort — remote skill registry query interface.

Defines the port for fetching, searching, and downloading skills from a
remote index (SkillHub).  The index is a JSON document hosted at a
configurable URL and contains metadata about community-contributed skills.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RemoteSkill:
    """A skill entry in the remote SkillHub index."""
    name: str
    version: str
    description: str
    author: str = ""
    download_url: str = ""
    sha256: str = ""
    homepage: str = ""
    tags: list[str] = field(default_factory=list)
    min_weebot_version: str = "0.0.0"
    dependencies: list[str] = field(default_factory=list)
    license: str = ""


class SkillIndexPort(ABC):
    """Query a remote skill registry (SkillHub)."""

    @abstractmethod
    async def fetch_index(self) -> list[RemoteSkill]:
        """Fetch the full skill index from the remote endpoint.

        Returns:
            A list of all remote skills.  An empty list on failure
            (network error, parse error) — never raises.
        """
        ...

    @abstractmethod
    async def search(self, query: str) -> list[RemoteSkill]:
        """Search the remote index by name, tag, or description.

        Args:
            query: Free-text search string.

        Returns:
            Matching skills sorted by relevance.  Empty list if
            the index could not be fetched or nothing matched.
        """
        ...

    @abstractmethod
    async def download(self, skill: RemoteSkill, target_dir: str) -> bool:
        """Download and verify a skill package to *target_dir*.

        Steps:
        1. ``GET`` the ``download_url``.
        2. Verify the downloaded bytes match ``sha256``.
        3. Extract the archive into ``target_dir``.
        4. Return ``True`` on success.

        Args:
            skill: The remote skill to download.
            target_dir: Absolute path to extract into.

        Returns:
            ``True`` if the download, verification, and extraction
            all succeeded.  ``False`` on any failure.
        """
        ...
