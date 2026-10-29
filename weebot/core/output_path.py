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


# Never written through a model-chosen path, whatever its location (audit 2026-10-29 R08,
# R13, R14). PathValidator.DENIED_BASENAMES reads the same set.
PROTECTED_BASENAMES: frozenset[str] = frozenset({
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.staging",
    ".env.test",
    "id_rsa",
    "id_ed25519",
    "id_dsa",
    "id_ecdsa",
})
# Whole-file writes never produce these; scripts are made by a human or the shell tool.
EXECUTABLE_SUFFIXES: frozenset[str] = frozenset({
    ".ps1", ".bat", ".cmd", ".sh", ".exe", ".dll", ".com", ".msi", ".scr", ".vbs", ".wsf",
})


def write_target(path: str, *, suffixes: frozenset[str] | None = None) -> str:
    """The absolute path a tool may write *path* to; ValueError says why it may not.

    Inside the project (``output_path``, then resolved, so a link cannot lead out), never a
    protected file (``.env``, SSH keys, anything under ``.git``) or an executable type, and,
    when the tool names the *suffixes* it produces, one of those. screen_capture, image_gen
    and video_gen wrote any path a model chose (R08, R14).
    """
    target = Path(output_path(path)).resolve(strict=False)
    if not target.is_relative_to(_PROJECT_ROOT):
        raise ValueError(f"Path escapes the workspace (project root): {path}")
    parts = [p.lower() for p in target.relative_to(_PROJECT_ROOT).parts]
    if target.name.lower() in PROTECTED_BASENAMES or ".git" in parts:
        raise ValueError(f"Refusing to write a protected file: {path}")
    suffix = target.suffix.lower()
    if suffix in EXECUTABLE_SUFFIXES:
        raise ValueError(f"Refusing to write an executable file: {path}")
    if suffixes is not None and suffix not in suffixes:
        allowed = ", ".join(sorted(suffixes))
        found = suffix or "no extension"
        raise ValueError(f"This tool writes {allowed} files, not {found}: {path}")
    if target.is_dir():
        raise ValueError(f"Path is a directory: {path}")
    return str(target)


def output_dir(relative: str) -> str:
    """Like ``output_path`` but ensures the parent directory exists.

    Creates parent directories as needed (``mkdir -p`` equivalent).
    Returns the absolute path.
    """
    resolved = output_path(relative)
    parent = os.path.dirname(resolved)
    os.makedirs(parent, exist_ok=True)
    return resolved
