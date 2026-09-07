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

logger = logging.getLogger(__name__)


class ApprovalMode(Enum):
    AUTO_APPROVE = "auto_approve"
    ALWAYS_ASK = "always_ask"
    DENY = "deny"
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


# Destructive PowerShell commands that always require confirmation
_DESTRUCTIVE_KEYWORDS: set[str] = {
    "remove-item",
    "del",
    "rm",
    "erase",
    "rd",
    "rmdir",
    "stop-process",
    "kill",
    "shutdown",
    "restart-computer",
    "clear-content",
    "set-content",
    "move-item",
    "rename-item",
    "copy-item",
}

# Built-in defaults: destructive → ask, format → deny, rest → auto
_DEFAULT_RULES: tuple[CommandRule, ...] = (
    # Allow Remove-Item / python writes inside the Output\ working directory
    # (checked before the blanket remove-item rule because longest-match wins)
    CommandRule(
        # Anchored to the whole command so chained commands don't match
        r"^remove-item\s+['\"]?[A-Za-z]:[\\\/][^;&|]*[Oo]utput[\\\/][^;&|]*$",
        ApprovalMode.AUTO_APPROVE,
        is_regex=True,
    ),
    CommandRule(
        r"open\s*\(\s*['\"].*[Oo]utput[\\\/].*['\"],\s*['\"]w",
        ApprovalMode.AUTO_APPROVE,
        is_regex=True,
    ),
    # Disk formatting — always denied
    CommandRule(
        r"\bformat\s+[a-zA-Z]:",
        ApprovalMode.DENY,
        is_regex=True,
        undo_hint="Formatting is irreversible. Use Diskpart carefully.",
    ),
    CommandRule(
        r"\bFormat-Volume\b",
        ApprovalMode.DENY,
        is_regex=True,
        undo_hint="Formatting is irreversible. Use Diskpart carefully.",
    ),
    # Registry editing — always ask
    CommandRule(
        r"\breg\s+(delete|add)",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Registry changes are system-wide and may require a reboot.",
    ),
    # User/group management — always ask
    CommandRule(
        r"\bnet\s+(user|localgroup)",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="User/group changes affect system security.",
    ),
    # ACL/permission changes — always ask
    CommandRule(
        r"\bicacls\b",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="ACL changes may lock out users or expose sensitive files.",
    ),
    CommandRule(
        r"\btakeown\b",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Taking ownership changes file access control.",
    ),
    # Boot configuration — always ask
    CommandRule(
        r"\bbcdedit\b",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Boot configuration changes can prevent the system from starting.",
    ),
    # Disk partition management — always ask
    CommandRule(
        r"\bdiskpart\b",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Disk partition changes may cause data loss.",
    ),
    # Scheduled tasks — always ask
    CommandRule(
        r"\bschtasks\b",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Scheduled tasks can run with system privileges.",
    ),
    # Environment variable injection via Set-Content
    CommandRule(
        r"\bSet-Content\b.*\$env:",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Modifying environment variables via Set-Content affects process behavior.",
    ),
    # Out-file targeting absolute paths outside workspace
    CommandRule(
        r"\bout-file\b.*[A-Za-z]:[\\\/](?!.*[Oo]utput[\\\/])",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Writing files outside the workspace may affect system state.",
    ),
    # Existing rules
    CommandRule(
        "remove-item",
        ApprovalMode.ALWAYS_ASK,
        undo_hint="Move to Recycle Bin first: Remove-Item -Confirm",
    ),
    CommandRule(
        "del ", ApprovalMode.ALWAYS_ASK, undo_hint="Consider 'move' instead of permanent delete."
    ),
    CommandRule("rm ", ApprovalMode.ALWAYS_ASK, undo_hint="Consider 'mv' to a temp folder first."),
    CommandRule(
        "stop-process",
        ApprovalMode.ALWAYS_ASK,
        undo_hint="Note the PID before stopping in case restart is needed.",
    ),
    CommandRule("kill", ApprovalMode.ALWAYS_ASK, undo_hint="Save PID/name before killing."),
    # Drive erase / wipe commands
    CommandRule(
        r"\brd\s",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Removing a directory via rd is permanent. Use Remove-Item -Confirm.",
    ),
    CommandRule(
        r"\berase\s",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="The erase command permanently deletes files.",
    ),
    CommandRule(
        r"\brmdir\s",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Removing a directory is permanent. Use Remove-Item -Confirm.",
    ),
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

    def __init__(self, rules: list[CommandRule] | None = None) -> None:
        # User rules first, then built-in defaults (frozen tuple — cast to list)
        self._rules = list(rules or []) + list(_DEFAULT_RULES)

        # Pre-compile regex patterns at init time so evaluate() never raises
        # re.error at runtime.
        #
        # An uncompilable rule used to be logged and SKIPPED, described in this
        # comment as "fail-open: the bad rule is ignored, all other rules still
        # apply". The rules include DENY entries, so a typo in one turned a
        # denial into an auto-approval, and nothing downstream could tell.
        #
        # We cannot know what a rule that will not compile was meant to catch.
        # The policy therefore records the breakage and asks a human for every
        # command while any rule is broken — a security gate that cannot run
        # its own rules does not report clean.
        self._compiled: dict[int, re.Pattern] = {}
        self._broken_rules: list[str] = []
        for i, rule in enumerate(self._rules):
            if rule.is_regex:
                try:
                    self._compiled[i] = re.compile(rule.pattern, re.IGNORECASE)
                except re.error as exc:
                    self._broken_rules.append(rule.pattern)
                    logger.error(
                        "ExecApprovalPolicy: invalid regex pattern %r "
                        "(rule index %d) — the policy will ASK for every command "
                        "until it is fixed: %s",
                        rule.pattern,
                        i,
                        exc,
                    )

    def evaluate(self, command: str, tool_category: str = "") -> ApprovalResult:
        if self._broken_rules:
            return ApprovalResult(
                command=command,
                approved=False,
                requires_confirmation=True,
                undo_hint="",
                reason=(
                    f"{len(self._broken_rules)} approval rule(s) failed to compile; "
                    "the policy cannot evaluate this command safely."
                ),
            )

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
        matches: list[CommandRule] = []
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

        # ── Defense-in-depth: chained destructive commands ──
        # Any command containing a command separator (;, &&, |) AND a
        # destructive keyword is bumped to ALWAYS_ASK regardless of the
        # longest-match result.  This prevents Output-folder bypass attacks
        # where a safe-looking rule matches a prefix before a chained
        # destructive action.
        _has_separator = bool(re.search(r"[;&|]", command))
        if _has_separator:
            for kw in _DESTRUCTIVE_KEYWORDS:
                if re.search(rf"\b{re.escape(kw)}\b", cmd_lower):
                    return ApprovalResult(
                        command=command,
                        approved=True,
                        requires_confirmation=True,
                        undo_hint="Chained destructive command detected.",
                        reason=f"Command contains separator with destructive keyword '{kw}'.",
                    )

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
            command=command, approved=True, requires_confirmation=False, undo_hint=""
        )


# ── Tool annotation tiers (MCP destructiveHint/readOnlyHint → approval) ─
# Maps annotation strings to ApprovalMode for the 3-tier HITL gate.
#   Tier 1 (auto_approve):   readOnlyHint=true  — safe, no side effects
#   Tier 2 (always_ask):     destructiveHint=false — notify user
#   Tier 3 (deny):           destructiveHint=true  — block, require explicit consent
TOOL_ANNOTATION_TIERS: dict[str, ApprovalMode] = {
    "read_only": ApprovalMode.AUTO_APPROVE,
    "destructive": ApprovalMode.DENY,
    "default": ApprovalMode.ALWAYS_ASK,
}


def get_approval_mode_from_annotation(
    read_only: bool = False, destructive: bool = False
) -> ApprovalMode:
    """Map MCP-style annotations to an approval tier.

    Args:
        read_only: ``readOnlyHint`` from the tool schema.
        destructive: ``destructiveHint`` from the tool schema.

    Returns:
        One of ``AUTO_APPROVE``, ``ALWAYS_ASK``, or ``DENY``.
    """
    if destructive:
        return ApprovalMode.DENY
    if read_only:
        return ApprovalMode.AUTO_APPROVE
    return ApprovalMode.ALWAYS_ASK


# ── Tool category tagging (Track 5 — Hermes Audit) ────────────────
# Maps tool categories to their required approval mode.
# Tools tagged ``finance`` or ``payment`` always require approval.
# Wrapped in MappingProxyType to prevent runtime mutation — any
# TOOL_CATEGORIES["key"] = val will raise TypeError.
TOOL_CATEGORIES: types.MappingProxyType = types.MappingProxyType(
    {
        "finance": ApprovalMode.FORCE_ALWAYS_ASK,
        "payment": ApprovalMode.FORCE_ALWAYS_ASK,
        # Inbound email is untrusted input (ADR 006). Any action that follows
        # an atomic_mail jmap_request must be confirmed before execution.
        "inbound_mail": ApprovalMode.FORCE_ALWAYS_ASK,
    }
)


def get_category_approval_mode(category: str) -> ApprovalMode:
    """Return the approval mode for a tool category.

    Args:
        category: Tool category string (e.g. "finance", "payment", "general").

    Returns:
        The ApprovalMode for that category. Unknown categories default to AUTO_APPROVE.
    """
    return TOOL_CATEGORIES.get(category.lower(), ApprovalMode.AUTO_APPROVE)
