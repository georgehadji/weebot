"""Ponytail prose truncation post-processor.

When Ponytail mode is active, models sometimes write one line of code followed
by paragraphs of justification. This service truncates trailing prose after
closing code fences while leaving code, tool outputs, and structured JSON
intact.
"""
from __future__ import annotations

import re


class PonytailPostProcessor:
    """Truncate trailing explanatory prose after code blocks."""

    MAX_PROSE_LINES = 3
    _CODE_FENCE_RE = re.compile(r"(```[\w]*\n.*?\n```)", re.DOTALL)

    def truncate(self, text: str) -> str:
        """Return *text* with trailing prose after the last code fence capped.

        Args:
            text: Assistant response that may contain code blocks followed by
                explanatory prose.

        Returns:
            The response with trailing prose truncated to ``MAX_PROSE_LINES``
            when Ponytail-style verbosity is detected. If there is no trailing
            code fence, *text* is returned unchanged.
        """
        if not text or not text.strip():
            return text

        parts = self._CODE_FENCE_RE.split(text)
        if len(parts) < 3:
            return text

        trailing = parts[-1]
        prose_lines = trailing.strip().split("\n")
        if len(prose_lines) <= self.MAX_PROSE_LINES:
            return text

        truncated = "\n".join(prose_lines[: self.MAX_PROSE_LINES])
        return "".join(parts[:-1]) + "\n" + truncated
