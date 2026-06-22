"""Tool-call argument repair — fixes common LLM output issues before validation.

Repair strategies (applied in order):
1. ``ast.literal_eval`` — handles Python repr (single quotes, True/False/None)
2. Regex fixes — trailing commas, single-quoted keys/values, unquoted dict keys
3. ``difflib`` — fuzzy tool-name matching for typos

Each strategy is tried independently; the first successful parse wins.
Non-repairable strings return ``None`` so the existing error path takes over.

This is distinct from ``normalize_tool_call_arguments()`` in the caching adapter
— that normalizes *already-valid* JSON for bit-stable cache prefixes, while this
repairs *invalid* JSON that would otherwise be rejected.
"""
from __future__ import annotations

import ast
import json
import logging
import re
from difflib import get_close_matches
from typing import Optional

logger = logging.getLogger(__name__)

# ── Public API ───────────────────────────────────────────────────────────────


def repair_json_string(raw: str) -> Optional[str]:
    """Attempt to repair a (possibly malformed) tool-call arguments JSON string.

    Tries multiple strategies in order of cost:
    1. Direct ``json.loads`` — already valid, no repair needed (fast path)
    2. ``ast.literal_eval`` — handles Python repr (``{'key': 'val'}``)
    3. Regex fixes — trailing commas, single quotes → double, unquoted keys

    Args:
        raw: Raw arguments string from LLM tool_call.

    Returns:
        Repaired JSON string, or ``None`` if all strategies failed.
    """
    if not raw or not raw.strip():
        return None

    # ── Strategy 0: already valid JSON — no repair needed ─────────
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass

    # ── Strategy 1: Python repr (Anthropic SDK, single quotes) ────
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, dict):
            repaired = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
            logger.debug("Repair[literal_eval]: %s -> %s", raw[:60], repaired[:60])
            return repaired
    except (ValueError, SyntaxError, MemoryError):
        pass

    # ── Strategy 2: regex fixes ───────────────────────────────────
    fixed = raw
    fixed = _fix_trailing_commas(fixed)
    fixed = _fix_single_quotes(fixed)
    fixed = _fix_unquoted_keys(fixed)

    try:
        json.loads(fixed)
        logger.debug("Repair[regex]: %s -> %s", raw[:60], fixed[:60])
        return fixed
    except json.JSONDecodeError:
        pass

    # All strategies exhausted
    return None


def fuzzy_match_tool_name(name: str, valid_names: list[str], cutoff: float = 0.6) -> Optional[str]:
    """Find the closest matching valid tool name for a (possibly typo'd) name.

    Uses ``difflib.get_close_matches`` with a default similarity cutoff of 0.6.
    Returns ``None`` when no match exceeds the cutoff.

    Args:
        name: The tool name from the LLM (may contain typos).
        valid_names: List of registered tool names.
        cutoff: Similarity threshold (0.0–1.0). Default 0.6.

    Returns:
        The closest matching valid name, or ``None``.
    """
    if not name or not valid_names:
        return None
    matches = get_close_matches(name, valid_names, n=1, cutoff=cutoff)
    if matches:
        logger.info(
            "Fuzzy tool-name match: %r -> %r (cutoff=%.2f)",
            name, matches[0], cutoff,
        )
        return matches[0]
    return None


# ── Internal repair helpers ──────────────────────────────────────────────────


def _fix_trailing_commas(raw: str) -> str:
    """Remove trailing commas before ``}`` or ``]``."""
    return re.sub(r",\s*([}\]])", r"\1", raw)


def _fix_single_quotes(raw: str) -> str:
    """Replace single quotes with double quotes in JSON-like content.

    Only replaces single quotes that likely serve as JSON string delimiters
    (not apostrophes inside words). Uses a heuristic: replace ``'`` at the
    boundary of a value/colon/comma/bracket, but leaves ``'`` inside words.
    """
    # Strategy: replace single-quoted keys first: 'key':
    raw = re.sub(r"'([^']+)':", r'"\1":', raw)
    # Then replace single-quoted string values: : 'value'
    raw = re.sub(r":\s*'([^']*)'", r': "\1"', raw)
    # Then handle lone single quotes around values after commas
    raw = re.sub(r",\s*'([^']*)'", r', "\1"', raw)
    return raw


def _fix_unquoted_keys(raw: str) -> str:
    """Add double quotes around unquoted dict keys (identifiers before ``:``).

    Handles cases like ``{key: "value"}`` → ``{"key": "value"}``.
    Does NOT re-quote already-quoted keys or numeric indices.
    """
    # Match unquoted identifiers (word chars) before ':' inside dicts
    raw = re.sub(r"([{,])\s*([A-Za-z_]\w*)\s*:", r'\1"\2":', raw)
    return raw
