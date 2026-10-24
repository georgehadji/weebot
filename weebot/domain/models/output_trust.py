"""OutputTrust — how far a tool's output may be trusted before it enters the prompt.

A property of the tool *type*, declared next to the tool, instead of a name list
kept somewhere else that nobody remembers to update (SEC-1 of
``tasks/specs/arch_audit_2026_10_remediation_plan.md``). The default on
``BaseTool`` is the safe one: a tool nobody classified is fenced and taints the
session until someone reviews it and declares it ``LOCAL``.

The decisions that follow from a value (fence? taint?) are pure functions in
``weebot.core.trust_boundary``.
"""

from __future__ import annotations

from enum import StrEnum


class OutputTrust(StrEnum):
    """Who can choose the text a tool returns."""

    # Text a third party can author: pages, search results, mail, OCR of
    # arbitrary media, MCP servers. Fenced, and taints the session so later
    # egress needs approval. The default.
    EXTERNAL = "external"

    # A fixed-schema, single-origin endpoint whose text no third party chooses
    # (weather). Fenced, but does not taint: over-approval trains users to
    # disable the guard.
    FIXED_SCHEMA = "fixed"

    # Produced inside this process or by the user's own machine and notes.
    # Neither fenced nor tainting. Declaring it is a reviewed security decision.
    LOCAL = "local"
