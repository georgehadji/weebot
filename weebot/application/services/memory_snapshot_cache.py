"""The persistent-memory text for the system prompt, read once per session (H24a).

The snapshot used to be re-read from disk at every step, so a memory write by any
session changed the prompt prefix of every running one and no prompt cache could hold.
Now the first step of a session reads it and later steps reuse that text. A write goes
to disk at once and shows up in the next session; inside the session the model already
has it in the tool result.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable

MAX_SESSIONS = 256
"""Sessions kept before the least recently used is dropped."""


class MemorySnapshotCache:
    """A bounded LRU of snapshot text keyed by session id."""

    def __init__(
        self,
        load: Callable[[], Awaitable[str]],
        frozen: Callable[[], bool] = lambda: True,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        self._load = load
        self._frozen = frozen
        self._max = max_sessions
        self._by_session: OrderedDict[str, str] = OrderedDict()

    async def get(self, session_id: str) -> str:
        """The snapshot for *session_id*: read now, or the one read at its first step."""
        if not self._frozen():
            return await self._load()
        if session_id in self._by_session:
            self._by_session.move_to_end(session_id)
            return self._by_session[session_id]
        text = await self._load()
        # Two first steps racing both read; the first to finish wins, so the text is stable.
        text = self._by_session.setdefault(session_id, text)
        while len(self._by_session) > self._max:
            self._by_session.popitem(last=False)
        return text

    async def forget(self, session_id: str) -> None:
        """Drop *session_id*; async because the deletion orchestrator awaits every purge."""
        self._by_session.pop(session_id, None)
