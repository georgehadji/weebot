"""What the model last saw of each file, so a write over a changed file is refused (H6).

``view`` (and every successful write) records a stamp of the file. Before a later write
the tool asks ``check``: a file nobody viewed, or one that changed since, is not safe to
overwrite from memory. One registry per tool collection (``Container.tool_wiring``);
``purge`` drops every stamp, for a session-delete cascade.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from pathlib import Path
from typing import NamedTuple


class _Stamp(NamedTuple):
    mtime_ns: int
    size: int
    sha256: str


def _stamp(path: Path) -> _Stamp:
    stat = path.stat()
    return _Stamp(stat.st_mtime_ns, stat.st_size, hashlib.sha256(path.read_bytes()).hexdigest())


class FileStateRegistry:
    def __init__(self, capacity: int = 512) -> None:
        self._capacity = capacity
        self._seen: OrderedDict[str, _Stamp] = OrderedDict()

    def record(self, path: Path) -> None:
        """Remember the file as it is now. A file that cannot be read is forgotten."""
        key = str(path)
        try:
            self._seen[key] = _stamp(path)
        except OSError:
            self._seen.pop(key, None)
            return
        self._seen.move_to_end(key)
        while len(self._seen) > self._capacity:
            self._seen.popitem(last=False)

    def check(self, path: Path) -> str | None:
        """None when a write is safe, else the reason it is not."""
        key = str(path)
        known = self._seen.get(key)
        if known is None:
            return "you have not viewed this file; view it before editing it"
        try:
            stat = path.stat()
            if (stat.st_mtime_ns, stat.st_size) == (known.mtime_ns, known.size):
                return None
            if _stamp(path).sha256 == known.sha256:  # touched, not changed
                self.record(path)
                return None
        except OSError:
            return None  # gone or unreadable: the write reports that itself
        return "file changed since you last viewed it; view it again"

    def purge(self) -> None:
        self._seen.clear()
