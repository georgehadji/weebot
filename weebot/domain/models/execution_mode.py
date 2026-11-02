"""ExecutionMode — controls how the flow interacts with the human operator.

Pure domain model: no imports from Application or Infrastructure.
"""

from __future__ import annotations

from enum import StrEnum


class ExecutionMode(StrEnum):
    """Whether the flow pauses for human input during execution.

    ``INTERACTIVE`` is the current default: gates pause, tool calls ask for
    approval, AskHumanTool halts.  ``AUTO`` skips every pause — the whole
    plan runs without human interaction.

    The string serialisation matches the CLI flag names (``--auto`` /
    ``--interactive``).
    """

    AUTO = "auto"
    """Run entirely without human pauses — gates auto-approve, tool calls
    auto-grant, AskHumanTool is treated as a log message."""

    INTERACTIVE = "interactive"
    """Default: pause for gates, approval requests, and AskHumanTool as
    each component's own policy dictates."""

    @classmethod
    def from_flag(cls, flag: str | None) -> ExecutionMode:
        """Parse a CLI flag value, defaulting to ``INTERACTIVE``."""
        if flag is None:
            return cls.INTERACTIVE
        norm = flag.strip().lower()
        if norm in ("auto", "1", "true", "yes"):
            return cls.AUTO
        return cls.INTERACTIVE
