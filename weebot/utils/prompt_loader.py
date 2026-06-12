"""Prompt loader — loads prompt templates from config/prompts/ with inline fallback.

Single source of truth for prompt loading.  All agents use this instead of
hardcoding inline prompts.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "config" / "prompts"


def load_prompt_with_fallback(filename: str, default: str) -> str:
    """Load *filename* from config/prompts/, falling back to *default*.

    The default string serves as documentation of the prompt's intent
    and as a runtime fallback if the file is missing or unreadable.
    """
    path = _PROMPTS_DIR / filename
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception:
        logger.debug("Failed to read prompt file %s — using inline fallback", path, exc_info=True)
    return default
