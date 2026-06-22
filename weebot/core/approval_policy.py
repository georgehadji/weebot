"""Granular command execution approval policy (ported from OpenClaw).

CRITICAL: This policy runs on Windows 11 + PowerShell 5.1.
- ALL shell commands MUST use PowerShell-native syntax (Get-ChildItem, not ls).
- Safe display cmdlets (Format-Table, Format-List, Format-Wide) are AUTO_APPROVED.
- Disk formatting (format C:, Format-Volume) remains DENIED.
- Python str.format() and similar are NO LONGER blanket-denied (false-positive source).
"""
from __future__ import annotations

import logging
import re
import types
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ApprovalMode(Enum):
    AUTO_APPROVE = "auto_approve"
    ALWAYS_ASK   = "always_ask"
    DENY         = "deny"
    FORCE_ALWAYS_ASK = "force_always_ask"  # Bypasses all normal rules; always asks.


@dataclass(frozen=True)
class CommandRule:
    pattern: str
    mode: ApprovalMode
    is_regex: bool = False
    undo_hint: str = ""


@dataclass
class ApprovalResult:
    command: str
    approved: bool
    requires_confirmation: bool
    undo_hint: str
    reason: str = ""


# Built-in defaults: destructive → ask, format → deny, rest → auto
_DEFAULT_RULES: tuple[CommandRule, ...] = (
    # Allow Remove-Item / python writes inside the Output\ working directory
    # (checked before the blanket remove-item rule because longest-match wins)
    CommandRule(
        r"remove-item\s+['\"]?[A-Za-z]:[\\\/].*[Oo]utput[\\\/]",
        ApprovalMode.AUTO_APPROVE, is_regex=True,
    ),
    CommandRule(
        r"open\s*\(\s*['\"].*[Oo]utput[\\\/].*['\"],\s*['\"]w",
        ApprovalMode.AUTO_APPROVE, is_regex=True,
    ),
    CommandRule(r"\bformat\s+[a-zA-Z]:", ApprovalMode.DENY, is_regex=True,
                undo_hint="Formatting is irreversible. Use Diskpart carefully."),
    CommandRule(r"\bFormat-Volume\b", ApprovalMode.DENY, is_regex=True,
                undo_hint="Formatting is irreversible. Use Diskpart carefully."),
    CommandRule("remove-item", ApprovalMode.ALWAYS_ASK,
                undo_hint="Move to Recycle Bin first: Remove-Item -Confirm"),
    CommandRule("del ", ApprovalMode.ALWAYS_ASK,
                undo_hint="Consider 'move' instead of permanent delete."),
    CommandRule("rm ", ApprovalMode.ALWAYS_ASK,
                undo_hint="Consider 'mv' to a temp folder first."),
    CommandRule("stop-process", ApprovalMode.ALWAYS_ASK,
                undo_hint="Note the PID before stopping in case restart is needed."),
    CommandRule("kill", ApprovalMode.ALWAYS_ASK,
                undo_hint="Save PID/name before killing."),
)


# ── Frozen sentinel ──────────────────────────────────────────────────────────
# Once this module is loaded, its permission data structures are immutable.
# Any code attempting to mutate _DEFAULT_RULES or TOOL_CATEGORIES at runtime
# will get a TypeError (tuple/MappingProxyType). This prevents accidental or
# malicious permission widening after import.
_FROZEN: bool = True


class ExecApprovalPolicy:
    """
    Evaluates whether a shell command needs confirmation or should be denied.
    Rules are checked longest-match first (most specific wins).
    """

    def __init__(self, rules: Optional[List[CommandRule]] = None) -> None:
        # User rules first, then built-in defaults (frozen tuple — cast to list)
        self._rules = list(rules or []) + list(_DEFAULT_RULES)

        # Pre-compile regex patterns at init time so evaluate() never raises
        # re.error at runtime.  Invalid patterns are logged and silently skipped
        # (fail-open: the bad rule is ignored, all other rules still apply).
        self._compiled: Dict[int, re.Pattern] = {}
        for i, rule in enumerate(self._rules):
            if rule.is_regex:
                try:
                    self._compiled[i] = re.compile(rule.pattern, re.IGNORECASE)
                except re.error as exc:
                    logger.error(
                        "ExecApprovalPolicy: invalid regex pattern %r "
                        "(rule index %d) will be SKIPPED — %s",
                        rule.pattern, i, exc,
                    )

    def evaluate(self, command: str, tool_category: str = "") -> ApprovalResult:
        # ── Tool-category override: financial tools always ask ──────
        if tool_category:
            category_mode = get_category_approval_mode(tool_category)
            if category_mode == ApprovalMode.FORCE_ALWAYS_ASK:
                return ApprovalResult(
                    command=command,
                    approved=True,
                    requires_confirmation=True,
                    undo_hint="",
                    reason=f"Financial tool '{command[:80]}' requires explicit approval.",
                )

        cmd_lower = command.lower()

        # Find all matching rules, pick the most specific (longest pattern match)
        matches: List[CommandRule] = []
        for i, rule in enumerate(self._rules):
            if rule.is_regex:
                compiled = self._compiled.get(i)
                if compiled is None:
                    continue  # invalid pattern at init time — skip safely
                if compiled.search(command):
                    matches.append(rule)
            else:
                if rule.pattern.lower() in cmd_lower:
                    matches.append(rule)

        if matches:
            # Most specific = longest pattern
            best = max(matches, key=lambda r: len(r.pattern))
            if best.mode in (ApprovalMode.DENY,):
                return ApprovalResult(
                    command=command,
                    approved=False,
                    requires_confirmation=False,
                    undo_hint=best.undo_hint,
                    reason=f"Command denied by policy: {best.pattern}",
                )
            if best.mode in (ApprovalMode.FORCE_ALWAYS_ASK, ApprovalMode.ALWAYS_ASK):
                return ApprovalResult(
                    command=command,
                    approved=True,
                    requires_confirmation=True,
                    undo_hint=best.undo_hint,
                    reason="Confirmation required before execution.",
                )
            # AUTO_APPROVE
            return ApprovalResult(
                command=command,
                approved=True,
                requires_confirmation=False,
                undo_hint=best.undo_hint,
            )

        # No rule matched → auto-approve
        return ApprovalResult(
            command=command,
            approved=True,
            requires_confirmation=False,
            undo_hint="",
        )


# ── Tool category tagging (Track 5 — Hermes Audit) ────────────────
# Maps tool categories to their required approval mode.
# Tools tagged ``finance`` or ``payment`` always require approval.
# Wrapped in MappingProxyType to prevent runtime mutation — any
# TOOL_CATEGORIES["key"] = val will raise TypeError.
TOOL_CATEGORIES: types.MappingProxyType = types.MappingProxyType({
    "finance": ApprovalMode.FORCE_ALWAYS_ASK,
    "payment": ApprovalMode.FORCE_ALWAYS_ASK,
    # Inbound email is untrusted input (ADR 006). Any action that follows
    # an atomic_mail jmap_request must be confirmed before execution.
    "inbound_mail": ApprovalMode.FORCE_ALWAYS_ASK,
})


def get_category_approval_mode(category: str) -> ApprovalMode:
    """Return the approval mode for a tool category.

    Args:
        category: Tool category string (e.g. "finance", "payment", "general").

    Returns:
        The ApprovalMode for that category. Unknown categories default to AUTO_APPROVE.
    """
    return TOOL_CATEGORIES.get(category.lower(), ApprovalMode.AUTO_APPROVE)
