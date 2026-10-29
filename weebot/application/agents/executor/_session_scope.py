"""The owner of the executor's per-session security state (WB-03).

Taint, "the tab was last navigated to a local page", "this session wrote that file" and
"this session's flags were already replayed" are per-session facts that a fresh
``ToolExecutor`` cannot hold: one executor is built per step, so instance state does not
survive long enough.

They used to be four module-level containers in ``_tool_executor.py``, mutated from
anywhere in the module and never emptied -- production code only ever added. A web
process therefore kept one entry per session that had ever run a tool, each with the set
of paths that session wrote, for as long as the process lived. The only code that ever
removed an entry was a test fixture.

The event store is still the record: every change is also appended as a ``session_flag``
row and replayed by ``ToolExecutor._hydrate_session_state``. These are caches over it,
which is what makes closing one safe -- a session that comes back re-hydrates.

``close()`` is the lifecycle, and it must stay bound to a session's life (terminal state
or deletion). Do not put a TTL on it: dropping ``tainted`` while the session is still
live is exactly how the egress guard would stop requiring approval for outbound calls in
a session that has already read untrusted content.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SessionScope:
    """Per-session in-memory caches, with an explicit lifecycle.

    Not thread-safe by design: it is touched only from the event loop, like the
    executor that owns it.
    """

    def __init__(self) -> None:
        self._tainted: set[str] = set()
        self._local_tab: dict[str, bool] = {}
        self._written_files: dict[str, set[str]] = {}
        self._hydrated: set[str] = set()

    # ── Taint ────────────────────────────────────────────────────────────────

    def is_tainted(self, session_id: str) -> bool:
        """True once untrusted external content has entered this session."""
        return session_id in self._tainted

    def mark_tainted(self, session_id: str) -> bool:
        """Taint *session_id*; return True only if it was not already tainted.

        The return value is what stops the caller appending a duplicate
        ``session_flag`` row for a session tainted on every step.
        """
        if not session_id or session_id in self._tainted:
            return False
        self._tainted.add(session_id)
        return True

    # ── Browser tab locality ─────────────────────────────────────────────────

    def local_tab(self, session_id: str) -> bool | None:
        """Whether the last navigation was local, or None if it never navigated."""
        return self._local_tab.get(session_id)

    def set_local_tab(self, session_id: str, local: bool) -> bool:
        """Record the tab's locality; return True only if it changed."""
        if self._local_tab.get(session_id) == local:
            return False
        self._local_tab[session_id] = local
        return True

    # ── Files this session wrote ─────────────────────────────────────────────

    def wrote_file(self, session_id: str, path: str) -> bool:
        """True if *session_id* itself wrote *path* (viewing it adds no new content)."""
        return path in self._written_files.get(session_id, ())

    def note_written_file(self, session_id: str, path: str) -> bool:
        """Record a file write; return True only if it was not already recorded."""
        written = self._written_files.setdefault(session_id, set())
        if path in written:
            return False
        written.add(path)
        return True

    # ── Hydration marker ─────────────────────────────────────────────────────

    def claim_hydration(self, session_id: str) -> bool:
        """Return True the first time this process replays *session_id*'s flags."""
        if not session_id or session_id in self._hydrated:
            return False
        self._hydrated.add(session_id)
        return True

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def close(self, session_id: str) -> None:
        """Drop everything remembered about *session_id*.

        Safe while the session's flags are in the store: a later turn re-hydrates them.
        Call it when a session reaches a terminal state or is deleted -- never on a
        timer (see the module docstring).
        """
        if not session_id:
            return
        self._tainted.discard(session_id)
        self._local_tab.pop(session_id, None)
        self._written_files.pop(session_id, None)
        self._hydrated.discard(session_id)

    def clear(self) -> None:
        """Forget every session. For tests and process teardown."""
        self._tainted.clear()
        self._local_tab.clear()
        self._written_files.clear()
        self._hydrated.clear()

    def __len__(self) -> int:
        """How many sessions are currently tracked, by any of the four caches."""
        return len(
            set(self._tainted)
            | set(self._local_tab)
            | set(self._written_files)
            | self._hydrated
        )


# Built at import: the constructor only makes empty containers and touches no event
# loop, so there is nothing to defer. Same shape as `core.background_tasks`, which is
# this repository's idiom for "something process-wide that needs an owner".
_DEFAULT_SCOPE = SessionScope()


def get_session_scope() -> SessionScope:
    """The process-wide scope, for the executor and for the code that closes sessions."""
    return _DEFAULT_SCOPE


def keep_private(models: list[str]) -> list[str]:
    """*models* minus free tiers that train on prompts, once this session read untrusted content.

    The cascade applies it to every list it tries, so a tainted session's prompts (fetched
    pages, mail, file contents) never reach such a provider.
    """
    from weebot.config.free_models import trains_on_prompts
    from weebot.core.log_context import session_id_var

    training = [m for m in models if m and trains_on_prompts(m)]
    if not training or not _DEFAULT_SCOPE.is_tainted(session_id_var.get() or ""):
        return models
    logger.info("untrusted content in this session: skipping %d free model(s)", len(training))
    return [m for m in models if m not in training]
