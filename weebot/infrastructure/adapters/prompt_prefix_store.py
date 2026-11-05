"""In-memory PromptPrefixStore: a bounded LRU, one record per session (H10)."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable

from weebot.application.ports.prompt_prefix_port import PromptPrefixStore

MAX_SESSIONS = 256


class InMemoryPromptPrefixStore(PromptPrefixStore):
    """*on_change* is called with the reason each time a session's prefix changes."""

    def __init__(
        self, on_change: Callable[[str], None] | None = None, max_sessions: int = MAX_SESSIONS
    ) -> None:
        self._on_change = on_change
        self._max = max_sessions
        self._last: OrderedDict[str, tuple[str, str]] = OrderedDict()

    def record(self, session_id: str, system_sha: str, tools_sha: str) -> str | None:
        previous = self._last.pop(session_id, None)
        self._last[session_id] = (system_sha, tools_sha)
        while len(self._last) > self._max:
            self._last.popitem(last=False)
        if previous is None or previous == (system_sha, tools_sha):
            return None
        system_changed = previous[0] != system_sha
        tools_changed = previous[1] != tools_sha
        if system_changed and tools_changed:
            reason = "both"
        else:
            reason = "system" if system_changed else "tools"
        if self._on_change is not None:
            self._on_change(reason)
        return reason

    async def forget(self, session_id: str) -> None:
        self._last.pop(session_id, None)
