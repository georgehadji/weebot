"""Approval scopes (H18b): let a human's yes cover a kind of command, not one exact call.

A grant (``ApprovalManager``) covers one exact call once. A scope covers every call with the
same *command pattern* (``npm test``, ``git push --force-with-lease``): ``session`` until the
session ends, ``always`` for good, kept in ``~/.weebot/approvals.json``.

Only a call no rule covers can be scoped (``GuardVerdict.scopable``). DANGEROUS commands,
approval floors and the untrusted-content gate (D5) never carry a pattern, so no scope can
reach them.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import tempfile
import threading
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

Scope = Literal["session", "always"]

# Anything that chains, redirects or substitutes: such a line is not one command.
_COMPOUND = re.compile(r"[;&|<>`$(){}\r\n]")
_WORD = re.compile(r"^[A-Za-z0-9][\w.:+-]*$")


def command_pattern(command: str) -> str | None:
    """``argv[0]``, its subcommand and its flags without values; None when not one plain command.

    ``npm test --silent`` -> ``npm test --silent``; ``git push origin main`` -> ``git push``.
    shortcut: the words after the subcommand are ignored, so ``npm run build`` and
    ``npm run deploy`` share a pattern; upgrade by keying the script name for runners.
    """
    text = command.strip()
    if not text or _COMPOUND.search(text):
        return None
    try:
        words = [w.strip("'\"") for w in shlex.split(text, posix=False)]
    except ValueError:
        return None
    if not words:
        return None
    program = re.split(r"[\\/]", words[0])[-1].lower().removesuffix(".exe")
    if not _WORD.match(program):
        return None
    rest = words[1:]
    sub = rest[0] if rest and not rest[0].startswith("-") else None
    if sub is not None and not _WORD.match(sub):
        return None
    if sub is None and any(not w.startswith("-") for w in rest):
        return None  # `python -m pytest`: a flag's value could be anything, so no pattern
    flags = sorted({w.split("=", 1)[0].lower() for w in rest if w.startswith("-")})
    return " ".join([program, *([sub] if sub else []), *flags])


def _default_path() -> Path:
    return Path.home() / ".weebot" / "approvals.json"


class ScopedGrants:
    """Session and always scopes, by command pattern."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_path()
        self._session: dict[str, set[str]] = {}
        self._always: set[str] | None = None  # read on first use
        self._lock = threading.Lock()

    def allows(self, session_id: str, pattern: str | None) -> Scope | None:
        """The scope that covers *pattern* in this session, or None."""
        if not pattern:
            return None
        with self._lock:
            if pattern in self._session.get(session_id, ()):
                return "session"
            if pattern in self._load_always():
                return "always"
        return None

    def grant(self, scope: Scope, session_id: str, pattern: str) -> None:
        with self._lock:
            if scope == "session":
                self._session.setdefault(session_id, set()).add(pattern)
            else:
                always = self._load_always()
                always.add(pattern)
                self._save(always)
        logger.info("approval scope granted: %s %r", scope, pattern)

    def forget_session(self, session_id: str) -> None:
        with self._lock:
            self._session.pop(session_id, None)

    def _load_always(self) -> set[str]:
        if self._always is None:
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._always = {p for p in data.get("always", []) if isinstance(p, str)}
            except FileNotFoundError:
                self._always = set()
            except (OSError, ValueError, AttributeError) as exc:
                logger.warning("approvals file unreadable, no 'always' scopes: %s", exc)
                self._always = set()
        return self._always

    def _save(self, always: set[str]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"always": sorted(always)}, handle, indent=2)
            os.replace(tmp, self._path)
        except OSError as exc:
            logger.warning("could not save the approvals file: %s", exc)
