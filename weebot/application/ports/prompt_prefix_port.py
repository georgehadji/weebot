"""PromptPrefixStore: remembers each session's last request prefix (H10).

Prompt caching only pays if the prefix of a request equals the previous one. This port
records the hash of the system text and of the tool definitions per session and says
what changed, so the change can be counted and a regression found.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class PromptPrefixStore(ABC):
    @abstractmethod
    def record(self, session_id: str, system_sha: str, tools_sha: str) -> str | None:
        """Store this request's prefix hashes.

        Returns None for a session's first request or an unchanged prefix, otherwise
        what changed: ``"system"``, ``"tools"`` or ``"both"``.
        """

    @abstractmethod
    async def forget(self, session_id: str) -> None:
        """Drop a session's record."""
