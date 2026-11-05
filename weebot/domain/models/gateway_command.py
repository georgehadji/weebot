"""What a gateway slash command asks for (H28).

A closed set of frozen values. The dispatcher returns one; each adapter maps the type to an
action. It replaces sentinel strings (``OK_SET_MODEL:x``) that an adapter had to parse back out
of text, and that reached the user unchanged when the adapter did not know them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reply:
    """Just say this."""

    text: str


@dataclass(frozen=True)
class NewSession:
    """Drop the chat's session and start fresh (/new, /reset)."""


@dataclass(frozen=True)
class StopRun:
    """Cancel the run in progress (/stop)."""


@dataclass(frozen=True)
class SetModel:
    model: str


@dataclass(frozen=True)
class ResumeSession:
    """Go back to the chat's last session (/resume)."""


@dataclass(frozen=True)
class ListTools:
    """/tools"""


@dataclass(frozen=True)
class McpStatus:
    """/mcp"""


@dataclass(frozen=True)
class Compress:
    """/compress"""


CommandResult = (
    Reply | NewSession | StopRun | SetModel | ResumeSession | ListTools | McpStatus | Compress
)
