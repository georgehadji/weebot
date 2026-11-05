"""Where a conversation can be cut (H21): pure functions over ``Session.events``.

A turn starts at a user ``MessageEvent`` and runs to the next one. A cut keeps everything before
a boundary and drops the rest.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from weebot.domain.models.event import AgentEvent, MessageEvent


@dataclass(frozen=True)
class Boundary:
    index: int  # position of the user message in the event list
    event_id: str
    text: str


def turn_boundaries(events: Sequence[AgentEvent]) -> list[Boundary]:
    """The user messages of the conversation, oldest first."""
    return [
        Boundary(i, e.id, e.message)
        for i, e in enumerate(events)
        if isinstance(e, MessageEvent) and e.role == "user"
    ]


def cut_back(
    events: Sequence[AgentEvent], turns: int
) -> tuple[list[AgentEvent], list[AgentEvent], Boundary]:
    """Drop the last *turns* turns. Returns (kept, dropped, boundary of the first dropped turn)."""
    boundaries = turn_boundaries(events)
    if turns < 1 or turns > len(boundaries):
        raise ValueError(f"cannot rewind {turns} turn(s): the conversation has {len(boundaries)}")
    boundary = boundaries[-turns]
    return list(events[: boundary.index]), list(events[boundary.index :]), boundary


def cut_at(
    events: Sequence[AgentEvent], event_id: str
) -> tuple[list[AgentEvent], list[AgentEvent]]:
    """Split just after the event *event_id*. Returns (kept, dropped)."""
    for i, event in enumerate(events):
        if event.id == event_id:
            return list(events[: i + 1]), list(events[i + 1 :])
    raise ValueError(f"event {event_id!r} is not in this conversation")
