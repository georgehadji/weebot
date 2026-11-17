"""Port for checking that text still parses after an edit (H6)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class SyntaxCheckPort(ABC):
    @abstractmethod
    def check(self, path: str, text: str) -> list[str]:
        """Problems in *text*, judged by the extension of *path*; empty when fine or unknown."""
