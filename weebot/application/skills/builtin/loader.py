"""Loads optimizer prompt files from the builtin skills directory.

Prompts are stored as markdown files in:
    weebot/application/skills/builtin/optimizer/*.md
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_BUILTIN_DIR = Path(__file__).resolve().parent / "optimizer"

_CACHE: dict[str, str] = {}


def load_optimizer_prompt(name: str) -> str:
    """Load an optimizer prompt by name (without .md suffix).

    Args:
        name: Prompt file name, e.g. 'reflection_failure', 'ranking'.

    Returns:
        Prompt content string.

    Raises:
        FileNotFoundError: If the prompt file doesn't exist.
    """
    if name in _CACHE:
        return _CACHE[name]

    path = _BUILTIN_DIR / f"{name}.md"
    if not path.exists():
        # Fallback: check if the file exists with a different path scheme
        alt = _BUILTIN_DIR.parent / "optimizer" / f"{name}.md"
        if alt.exists():
            path = alt
        else:
            raise FileNotFoundError(
                f"Optimizer prompt '{name}' not found at {path}"
            )

    content = path.read_text(encoding="utf-8")
    _CACHE[name] = content
    return content


def list_available_prompts() -> list[str]:
    """Return names of all available optimizer prompt files."""
    if not _BUILTIN_DIR.exists():
        return []
    return [p.stem for p in _BUILTIN_DIR.glob("*.md")]
