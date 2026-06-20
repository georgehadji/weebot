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
        ValueError: If *relative* contains ``..`` traversal (security guard).
    """
    normalized = relative.replace("\\", "/")
    if ".." in normalized.split("/"):
        raise ValueError(f"Path traversal blocked: {relative}")

    # If already absolute and under the project root, return as-is
    abs_path = os.path.abspath(relative)
    project_str = str(_PROJECT_ROOT).replace("\\", "/")
    if abs_path.replace("\\", "/").startswith(project_str):
        return abs_path

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
