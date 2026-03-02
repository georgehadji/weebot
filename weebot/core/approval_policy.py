"""Granular command execution approval policy (ported from OpenClaw)."""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

_log = logging.getLogger(__name__)


class ApprovalMode(Enum):
    AUTO_APPROVE = "auto_approve"
    ALWAYS_ASK   = "always_ask"
    DENY         = "deny"


@dataclass
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
_DEFAULT_RULES: List[CommandRule] = [
    CommandRule("format", ApprovalMode.DENY,
                undo_hint="Formatting is irreversible. Use Diskpart carefully."),
    CommandRule("format-volume", ApprovalMode.DENY,
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
]


class ExecApprovalPolicy:
    """
    Evaluates whether a shell command needs confirmation or should be denied.
    Rules are checked longest-match first (most specific wins).
    """

    def __init__(self, rules: Optional[List[CommandRule]] = None) -> None:
        # User rules first, then built-in defaults
        self._rules = (rules or []) + _DEFAULT_RULES

        # Pre-compile regex patterns at init time so evaluate() never raises
        # re.error at runtime.  Invalid patterns are logged and silently skipped
        # (fail-open: the bad rule is ignored, all other rules still apply).
        self._compiled: Dict[int, re.Pattern] = {}
        for i, rule in enumerate(self._rules):
            if rule.is_regex:
                try:
                    self._compiled[i] = re.compile(rule.pattern, re.IGNORECASE)
                except re.error as exc:
                    _log.error(
                        "ExecApprovalPolicy: invalid regex pattern %r "
                        "(rule index %d) will be SKIPPED — %s",
                        rule.pattern, i, exc,
                    )

    def evaluate(self, command: str) -> ApprovalResult:
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
            if best.mode == ApprovalMode.DENY:
                return ApprovalResult(
                    command=command,
                    approved=False,
                    requires_confirmation=False,
                    undo_hint=best.undo_hint,
                    reason=f"Command denied by policy: {best.pattern}",
                )
            if best.mode == ApprovalMode.ALWAYS_ASK:
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
