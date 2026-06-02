"""Regression test: FileSystemMemoryAdapter path traversal prevention.

BUG: _resolve() joined user-supplied ``file`` directly into the memory
directory path without validation.  An input like ``"../../../etc/passwd"``
escaped the memory directory, allowing writes to arbitrary filesystem
locations.

FIX: _resolve() now rejects ``file`` values containing ``..``, ``/``,
or ``\\`` before constructing the path.
"""
from __future__ import annotations

import pytest

from weebot.infrastructure.persistence.filesystem_memory import FileSystemMemoryAdapter


class TestResolveRejectsTraversal:
    """_resolve() must raise ValueError for path-traversal inputs."""

    @pytest.mark.parametrize("bad_input", [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\evil",
        "agent/../secret",
        "/etc/passwd",
        "subdir/file",
    ])
    def test_traversal_raises_valueerror(self, bad_input: str):
        adapter = FileSystemMemoryAdapter()
        with pytest.raises(ValueError, match="Invalid memory file name"):
            adapter._resolve(bad_input)

    @pytest.mark.parametrize("good_input", [
        "agent",
        "user",
        "AGENT",
        "my-memory-file",
        "session_notes_2024",
    ])
    def test_clean_names_accepted(self, good_input: str):
        adapter = FileSystemMemoryAdapter()
        path = adapter._resolve(good_input)
        # Path must be inside the memory directory
        assert path.parent == adapter._dir
        assert path.name == f"{good_input.upper()}.md"
