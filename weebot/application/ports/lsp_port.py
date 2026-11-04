"""LspPort: what a language server says about a file after an edit (H20).

``diagnostics`` answers ``None`` when the server has not replied within *timeout*; a caller
that wants the late answer asks again with a longer one. Every method is safe on a file the
port will not serve (no server installed, untrusted root): ``diagnostics`` answers ``[]``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.diagnostic import Diagnostic


class LspPort(ABC):
    @abstractmethod
    async def open(self, path: str, text: str) -> None:
        """Tell the server about *path* with its current *text* (a no-op once opened)."""

    @abstractmethod
    async def change(self, path: str, text: str) -> None:
        """Replace the server's copy of *path* with *text*, opening it first if needed."""

    @abstractmethod
    async def diagnostics(self, path: str, timeout: float) -> list[Diagnostic] | None:
        """The diagnostics for *path* after the last open or change, or ``None`` on timeout."""
