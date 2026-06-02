"""SteeringPort — non-blocking input channel for mid-execution user feedback.

Allows the user to inject steering messages ("spend less time on X",
"simplify, use fewer tools") into a running PlanActFlow without waiting
for an explicit ask_human pause.

Implementations:
- InMemorySteeringAdapter  — queue-based (CLI, single-process)
- WebSocketSteeringAdapter — routes through ConnectionManager (web)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class SteeringPort(ABC):
    """Non-blocking input channel for mid-execution user feedback.

    poll() is called by flow states between steps.  It must return
    immediately — never block waiting for input.
    """

    @abstractmethod
    async def poll(self, session_id: str) -> Optional[str]:
        """Return any pending steering input for *session_id*, or None.

        Must be non-blocking.  Called once per state transition in
        PlanActFlow / LeaderActFlow.
        """
        ...

    @abstractmethod
    async def send(self, session_id: str, message: str) -> None:
        """Queue a steering message for a running session.

        Called by input listeners (CLI stdin thread, WebSocket handler).
        Safe to call from any thread / coroutine.
        """
        ...
