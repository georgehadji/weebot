"""Durable persistence for small security-control state files.

Two halves of one property: **a persisted security decision survives a crash
and a bad parse.**

``Path.write_text`` truncates the file before writing it, so a write that dies
partway -- a full disk, a killed process, an evicted container -- leaves the
previous contents destroyed and the new ones incomplete. For a cache that is a
nuisance; for an access-control list it means an operator's deliberate decision
("this user is blocked", "this recipient is approved") is silently lost.

The load side matters just as much. A file that will not parse is *evidence*:
it is the only remaining record of what the control used to say. Substituting
defaults and then saving over it converts a recoverable problem into an
unrecoverable one.

Stdlib only, so this adds no import edge from ``weebot/core``.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

#: Suffix for a preserved copy of a file that could not be parsed. Matches the
#: ``*.corrupt.bak`` rule already present in .gitignore.
CORRUPT_SUFFIX = ".corrupt.bak"


def write_text_atomic(path: Path, data: str, encoding: str = "utf-8") -> None:
    """Replace *path* with *data* in one step, or leave it untouched.

    The temporary file is created in the destination directory so that
    ``os.replace`` is a same-filesystem rename, which is atomic. A failure at
    any point before the rename leaves the original file exactly as it was.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)
    except BaseException:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def preserve_unreadable(path: Path) -> Path | None:
    """Move an unparseable *path* aside so the next save cannot destroy it.

    Returns the path it was moved to, or ``None`` if there was nothing to
    preserve or the copy itself failed -- the caller is recovering from a
    failure already and must not be made to fail again by the recovery.
    """
    if not path.exists():
        return None
    kept = path.with_name(path.name + CORRUPT_SUFFIX)
    try:
        os.replace(path, kept)
    except OSError:
        logger.exception("could not preserve unreadable file %s", path)
        return None
    return kept
