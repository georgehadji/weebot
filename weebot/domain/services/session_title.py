"""Derive a short display title from a user's prompt.

A title is a label, so it costs nothing and cannot fail: no model call, no I/O. The web layer
shows ``derive_session_title(prompt)`` until the planner supplies a better title.
"""

from __future__ import annotations

import re

_FENCE = re.compile(r"^\s*(```|~~~)")
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_LEAD = re.compile(r"^[\s#>*+\-]+|^\d+[.)]\s+")
_NOISE = re.compile(r"[`*~]+")
_SPACE = re.compile(r"\s+")


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if _FENCE.match(line):
            continue
        if line.strip():
            return line
    return ""


def derive_session_title(text: str, max_len: int = 60) -> str:
    """First meaningful line of *text*, cleaned of markdown and cut at a word boundary."""
    line = _first_line(text or "")
    line = _LINK.sub(r"\1", line)
    bare_url = _URL.search(line)
    line = _URL.sub(" ", line)
    line = _NOISE.sub("", _LEAD.sub("", line))
    line = _SPACE.sub(" ", line).strip()
    if not line and bare_url:  # a prompt that is only a link: show the link without its scheme
        line = bare_url.group(0).split("://", 1)[1]
    if len(line) <= max_len:
        return line
    head = line[: max_len - 1]
    cut = head if line[max_len - 1] == " " else head.rsplit(" ", 1)[0]
    # Cut at a word boundary unless that throws away more than half of the title.
    return (cut if len(cut) >= max_len // 2 else head).rstrip() + "…"
