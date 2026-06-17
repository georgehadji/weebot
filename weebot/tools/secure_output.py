"""Secure Output File — writes sensitive data with restricted permissions.

Prevents LLM read-back of sensitive output by writing to a file with
0o600 permissions and optionally registering for cleanup.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any


class SecureOutputFile:
    """Writes content to a secure temporary file with restricted permissions.

    The file is created with 0o600 (owner read/write only) so that
    other processes on the system cannot read it.  Optionally registers
    for automatic cleanup.

    Usage:
        secure = SecureOutputFile()
        path = secure.write("sensitive API key")
        # path is only readable by the current process owner
        secure.cleanup()  # removes the file
    """

    def __init__(self, suffix: str = ".txt", prefix: str = "secure_") -> None:
        self._path: Path | None = None
        self._suffix = suffix
        self._prefix = prefix

    def write(self, content: str) -> Path:
        """Write *content* to a secure temp file.

        Returns:
            Path to the created file.
        """
        fd, tmp_path = tempfile.mkstemp(suffix=self._suffix, prefix=self._prefix)
        os.close(fd)

        path = Path(tmp_path)
        # Set strict permissions before writing
        path.chmod(0o600)
        path.write_text(content, encoding="utf-8")

        self._path = path
        return path

    def cleanup(self) -> None:
        """Remove the secure file if it exists."""
        if self._path and self._path.exists():
            try:
                self._path.unlink()
                self._path = None
            except OSError:
                pass

    @property
    def path(self) -> Path | None:
        return self._path

    def __enter__(self) -> "SecureOutputFile":
        return self

    def __exit__(self, *args: Any) -> None:
        self.cleanup()
