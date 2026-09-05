"""Output path resolver — always returns absolute paths under the project root.

Introduced to fix path inconsistency across tool calls.  Different tools
(bash, file_editor) resolve relative paths against different working
directories, causing files to be written outside the project or in
double-nested directories.
"""

from __future__ import annotations

import os
from pathlib import Path

# Cached at import time — the project root is the parent of the weebot package
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def output_path(relative: str) -> str:
    """Resolve a relative path to an absolute path under the project Output dir.

    Args:
        relative: A path relative to the project root, e.g. ``"Output/deps/file.txt"``
                  or ``"Output/review-batch/a.py"``.

    Returns:
        Absolute path, e.g. ``"E:/Documents/Vibe-Coding/weebot/Output/deps/file.txt"``.

    Raises:
        ValueError: If *relative* contains ``..`` traversal, or is an absolute
            path resolving outside the project root (security guard).
    """
    normalized = relative.replace("\\", "/")
    if ".." in normalized.split("/"):
        raise ValueError(f"Path traversal blocked: {relative}")

    # If already absolute and under the project root, return as-is.
    # is_relative_to compares path segments; the previous str.startswith test
    # also accepted any sibling whose name merely extends the root's.
    abs_path = Path(os.path.abspath(relative))
    if abs_path.is_relative_to(_PROJECT_ROOT):
        return str(abs_path)

    # ``_PROJECT_ROOT / relative`` DISCARDS the left operand when *relative* is
    # absolute (pathlib join semantics), so an absolute path outside the root
    # was handed back unchanged -- and output_dir() then os.makedirs() its
    # parent. Reject it instead of appearing to contain it.
    if os.path.isabs(relative):
        raise ValueError(f"Path escapes project root: {relative}")

    return str(_PROJECT_ROOT / relative)


def output_dir(relative: str) -> str:
    """Like ``output_path`` but ensures the parent directory exists.

    Creates parent directories as needed (``mkdir -p`` equivalent).
    Returns the absolute path.
    """
    resolved = output_path(relative)
    parent = os.path.dirname(resolved)
    os.makedirs(parent, exist_ok=True)
    return resolved
