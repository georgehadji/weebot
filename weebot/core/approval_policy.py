"""Granular command execution approval policy (ported from OpenClaw).

CRITICAL: This policy runs on Windows 11 + PowerShell 5.1.
- ALL shell commands MUST use PowerShell-native syntax (Get-ChildItem, not ls).
- Safe display cmdlets (Format-Table, Format-List, Format-Wide) are AUTO_APPROVED.
- Disk formatting (format C:, Format-Volume) remains DENIED.
- Python str.format() and similar are NO LONGER blanket-denied (false-positive source).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import shlex
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


_OVERWRITE_HINT = (
    "This overwrites a file already at the destination, and that file cannot be "
    "recovered. Check for name clashes first and keep both (add a suffix)."
)
# Where a PowerShell alias is the command and not a word in an argument: the start of
# the segment, or just inside a script block or parentheses.
_ALIAS_AT = r"(?:^|[{(])\s*"

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
    # Python writes inside the Output\ working directory. Shell file cmdlets
    # there are judged by _output_scoped() instead: the Remove-Item regex that
    # stood here matched any `\Output\` on any drive (C:\Windows\Output\x).
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
    CommandRule(
        r"\bClear-Disk\b",
        ApprovalMode.DENY,
        is_regex=True,
        undo_hint="Clearing a disk is irreversible.",
    ),
    # Deleting the OS or installed programs: denied, not asked. These and the
    # rules below were PowerShellTool's private lists (wave 6 G11); the guard
    # chain had no counterpart, and the tool itself consults only this policy.
    CommandRule(
        _ALIAS_AT
        + r"(?:Remove-Item|ri|rm|del|erase|rd|rmdir)\b.*\b[a-z]:\\(?:Windows|Program Files)\b",
        ApprovalMode.DENY,
        is_regex=True,
        undo_hint="Deleting Windows or Program Files breaks the system.",
    ),
    # Running code from a string or on another machine
    CommandRule(
        r"\bInvoke-Expression\b|" + _ALIAS_AT + r"iex\b(?!-)",
        ApprovalMode.DENY,
        is_regex=True,
        undo_hint="Invoke-Expression runs arbitrary code. Run the command directly.",
    ),
    CommandRule(
        r"\bInvoke-Command\b|" + _ALIAS_AT + r"icm\b(?!-)",
        ApprovalMode.DENY,
        is_regex=True,
        undo_hint="Invoke-Command runs code on another machine or session.",
    ),
    CommandRule(
        r"\bStart-Process\b.*\s-Credential\b",
        ApprovalMode.DENY,
        is_regex=True,
        undo_hint="Starting a process as another user is not allowed.",
    ),
    # Accounts and Windows features
    CommandRule(
        r"\b(?:New|Set)-LocalUser\b",
        ApprovalMode.DENY,
        is_regex=True,
        undo_hint="Creating or changing local accounts is not allowed.",
    ),
    CommandRule(
        r"\b(?:Add-WindowsCapability|Remove-WindowsFeature)\b",
        ApprovalMode.DENY,
        is_regex=True,
        undo_hint="Adding or removing Windows features is not allowed.",
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
    # The rules below were only in the uncalled CommandValidator and
    # tools/validation.py (D4); the live chain allowed these commands.
    CommandRule(
        r"\bcacls\b",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="ACL changes may lock out users or expose sensitive files.",
    ),
    # PowerShell accepts any prefix of -ExecutionPolicy, so -ex and -exec count too
    CommandRule(
        r"\s-(?:ep|ex\w*)\s+['\"]?(?:bypass|unrestricted)\b",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Bypassing the execution policy runs unsigned scripts. Review the script.",
    ),
    CommandRule(
        r"\bcipher\b[^;|&]*\s/w:",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="cipher /w overwrites all free space on the volume; it cannot be undone.",
    ),
    # Links make a path lead somewhere else, which defeats every path check after them
    CommandRule(
        r"\bnew-item\b[^;|]*-itemtype\s+['\"]?(symboliclink|symlink|junction|hardlink)\b|\bmklink\b",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Remove the link with `(Get-Item <path>).Delete()`; the target is untouched.",
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
    # Destructive cmdlets that only asked when chained (F05, ICM fix plan W3.3).
    CommandRule(
        r"\bset-content\b",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Set-Content overwrites the file; copy it first.",
    ),
    CommandRule(
        r"\bcopy-item\b",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Copy-Item overwrites an existing destination.",
    ),
    CommandRule(
        _ALIAS_AT + r"(?:cp|copy|cpi)\b(?!-)",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Copy-Item overwrites an existing destination.",
    ),
    CommandRule(
        r"\bmove-item\b",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Note the source path so the move can be reversed.",
    ),
    CommandRule(
        _ALIAS_AT + r"(?:mv|move|mi)\b(?!-)",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Note the source path so the move can be reversed.",
    ),
    # A forced move, copy or rename replaces the destination file: a deletion, not a
    # reversible move (de5d0990). The aliases count too, and so does any prefix of
    # -Force, which PowerShell accepts; an alias must be at command position, so
    # "notes-copy.txt" is no copy. Its hint wins over the plain rules' (_evaluate_segment).
    CommandRule(
        r"(?:\b(?:move-item|copy-item|rename-item)\b|"
        + _ALIAS_AT
        + r"(?:mv|move|mi|cp|copy|cpi)\b(?!-)).*\s-fo\w*",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint=_OVERWRITE_HINT,
    ),
    CommandRule(
        r"\b(?:mv|cp)\s+(?:-\w*f\w*|--force)\b",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint=_OVERWRITE_HINT,
    ),
    CommandRule(
        r"\b(?:move|copy|xcopy)\b.*\s/y\b",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint=_OVERWRITE_HINT,
    ),
    CommandRule(
        r"\brename-item\b",
        ApprovalMode.ALWAYS_ASK,
        is_regex=True,
        undo_hint="Note the old name so the rename can be reversed.",
    ),
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
    The command is split into segments; within a segment any matching DENY
    rule wins, else the longest matching pattern; across segments the
    strictest decision wins (DENY > ASK > AUTO_APPROVE).
    """

    def __init__(self, rules: list[CommandRule] | None = None) -> None:
        # User rules first, then built-in defaults (frozen tuple — cast to list)
        self._rules = list(rules or []) + list(_DEFAULT_RULES)
        self._n_user_rules = len(rules or [])  # the Output/ carve-out never overrides these

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

        # ── Pure fold over segments (ICM fix plan W3.3, F04) ──
        # The command is split on ; && || | & outside quotes and each segment
        # is judged alone, so an AUTO_APPROVE carve-out (the Output\ rule)
        # covers only its own segment. The strictest segment wins:
        # DENY > ASK > AUTO_APPROVE. The chained-keyword check used to
        # `return` ASK before DENY rules were read, so
        # `Format-Volume D; rm x` was asked about instead of denied.
        segments = _inline_literal_vars(split_segments(command))
        chained = len(segments) > 1
        decisions = [self._evaluate_segment(segment, chained) for segment in segments]
        worst = max(decisions, key=lambda d: d.rank, default=_NO_MATCH)

        if worst.rank == _RANK[ApprovalMode.DENY]:
            return ApprovalResult(
                command=command,
                approved=False,
                requires_confirmation=False,
                undo_hint=worst.undo_hint,
                reason=worst.reason,
            )
        if worst.rank == _RANK[ApprovalMode.ALWAYS_ASK]:
            return ApprovalResult(
                command=command,
                approved=True,
                requires_confirmation=True,
                undo_hint=worst.undo_hint,
                reason=worst.reason,
            )
        return ApprovalResult(
            command=command,
            approved=True,
            requires_confirmation=False,
            undo_hint=worst.undo_hint,
        )

    def unreviewed_segments(self, command: str) -> list[str]:
        """Segments no rule has an opinion on and that are not plain reads (audit A20).

        Evaluate approves these (default-allow); the shell guard decides what to do with
        them (record, or ask) so the default can be tightened in steps.
        """
        segments = _inline_literal_vars(split_segments(command))
        chained = len(segments) > 1
        return [
            s for s in segments
            if not self._evaluate_segment(s, chained).matched and not is_read_only_segment(s)
        ]

    def _evaluate_segment(self, segment: str, chained: bool) -> _SegmentDecision:
        """Judge one segment.

        Any DENY rule that matches wins, whatever its length: a longer
        ASK or AUTO_APPROVE pattern must not mask a denial (F05). Otherwise
        the longest matching pattern decides, which keeps carve-outs such as
        the Output\\ rule above the blanket rule they refine. With no rule,
        a destructive keyword in a chained command still asks.
        """
        seg_lower = segment.lower()
        matches = [
            rule
            for i, rule in enumerate(self._rules)
            if (
                self._compiled[i].search(segment)
                if rule.is_regex and i in self._compiled
                else (not rule.is_regex and rule.pattern.lower() in seg_lower)
            )
        ]
        denies = [r for r in matches if r.mode is ApprovalMode.DENY]
        user_rule_matched = any(r in self._rules[: self._n_user_rules] for r in matches)
        if not denies and not user_rule_matched and _output_scoped(segment):
            return _NO_MATCH
        if denies or matches:
            best = max(denies or matches, key=lambda r: len(r.pattern))
            # A warning that the command destroys a file outranks a milder hint from a
            # longer rule of the same mode ("the move can be reversed" for mv -f).
            hint = next(
                (r.undo_hint for r in matches
                 if r.undo_hint == _OVERWRITE_HINT and r.mode is best.mode),
                best.undo_hint,
            )
            if best.mode is ApprovalMode.DENY:
                reason = f"Command denied by policy: {best.pattern}"
            elif best.mode is ApprovalMode.AUTO_APPROVE:
                reason = ""
            else:
                reason = "Confirmation required before execution."
            return _SegmentDecision(_RANK[best.mode], reason, hint)
        if chained:
            for kw in sorted(_DESTRUCTIVE_KEYWORDS):
                if re.search(rf"\b{re.escape(kw)}\b", seg_lower):
                    return _SegmentDecision(
                        _RANK[ApprovalMode.ALWAYS_ASK],
                        f"Command contains separator with destructive keyword '{kw}'.",
                        "Chained destructive command detected.",
                    )
        return _UNMATCHED


@dataclass(frozen=True)
class _SegmentDecision:
    rank: int
    reason: str = ""
    undo_hint: str = ""
    matched: bool = True  # False only when no rule, carve-out or keyword said anything


_RANK: dict[ApprovalMode, int] = {
    ApprovalMode.AUTO_APPROVE: 0,
    ApprovalMode.ALWAYS_ASK: 1,
    ApprovalMode.FORCE_ALWAYS_ASK: 1,
    ApprovalMode.DENY: 2,
}
_NO_MATCH = _SegmentDecision(_RANK[ApprovalMode.AUTO_APPROVE])
_UNMATCHED = _SegmentDecision(_RANK[ApprovalMode.AUTO_APPROVE], matched=False)

# Commands that only read. A shell segment that matches no rule and is not one of these is
# "unreviewed": nothing in the policy has an opinion about it (audit A20). Data, not logic:
# extend it here when a harmless command keeps asking.
READ_ONLY_COMMANDS: frozenset[str] = frozenset({
    "ls", "dir", "cat", "type", "head", "tail", "wc", "grep", "findstr", "find", "echo", "pwd",
    "cd", "sl", "which", "where", "whoami", "hostname", "date", "tree", "stat", "file", "diff",
    "sort", "uniq", "cut", "basename", "dirname", "realpath", "env", "printenv",
    "gc", "gci", "gl", "gm", "gps", "select", "measure", "sls", "ft", "fl", "fw",
    "out-null", "sort-object", "where-object", "group-object", "write-output", "write-host",
    "test-path", "resolve-path", "split-path", "join-path",
})
_READ_ONLY_PREFIXES = ("get-", "select-", "measure-", "compare-", "test-")
_READ_ONLY_GIT = frozenset({"status", "log", "diff", "show", "rev-parse", "ls-files", "blame"})
# A segment holding any of these can write or run code whatever its first word is.
_NOT_PLAIN = ("::", ">", "{", "$(", chr(96))


def is_read_only_segment(segment: str) -> bool:
    """True for a plain read: a known read-only command with no redirect, script block or
    static call. Conservative on purpose: unknown means not read-only."""
    low = segment.strip().lower()
    if not low or any(mark in low for mark in _NOT_PLAIN):
        return False
    tokens = low.split()
    first = tokens[0].strip("&.\"'").replace(chr(92), "/").rsplit("/", 1)[-1].removesuffix(".exe")
    if first == "git":
        sub = next((t for t in tokens[1:] if not t.startswith("-")), "")
        return sub in _READ_ONLY_GIT
    if first == "find" and ("-delete" in low or "-exec" in low):
        return False
    return first in READ_ONLY_COMMANDS or first.startswith(_READ_ONLY_PREFIXES)


# File cmdlets the agent uses on its own Output/ work, and how each takes its
# positional arguments: "paths" (every one is a path), "path+value" (the first
# is a path, the rest are content), "path+name" (a path, then a bare new name).
_OUTPUT_CMDLETS: dict[str, str] = {
    "set-content": "path+value",
    "add-content": "path+value",
    "out-file": "path+value",
    "clear-content": "paths",
    "new-item": "paths",
    "remove-item": "paths",
    "move-item": "paths",
    "copy-item": "paths",
    "rename-item": "path+name",
}
_PATH_PARAMS = {"-path", "-literalpath", "-destination", "-filepath"}
_VALUE_PARAMS = {"-value", "-encoding", "-itemtype", "-filter", "-include", "-exclude"}
_NAME_PARAMS = {"-newname", "-name"}
_SWITCHES = {"-force", "-recurse", "-nonewline", "-append", "-passthru", "-confirm:$false"}
# `New-Item -ItemType` values that make a path lead somewhere else.
_LINK_TYPES = {"symboliclink", "symlink", "junction", "hardlink"}


def _in_output(path: str) -> bool:
    """True when *path* is strictly inside this workspace's Output/ folder."""
    p = path.strip("'\"").replace("\\", "/")
    if not p or "$" in p or "~" in p or ".." in p.split("/"):
        return False
    root = os.getcwd().replace("\\", "/").rstrip("/") + "/"
    if p.lower().startswith(root.lower()):
        p = p[len(root) :]
    elif re.match(r"^[A-Za-z]:/|^/", p):
        return False  # absolute, and not under this workspace
    p = p.removeprefix("./")
    head, _, rest = p.partition("/")
    if not (head.lower() == "output" and bool(rest)):
        return False
    # The text says Output/, but a junction or symlink inside it may lead elsewhere:
    # judge where the path really lands.
    try:
        real = (Path(os.getcwd()) / p).resolve(strict=False)
        return real.is_relative_to((Path(os.getcwd()) / head).resolve(strict=False))
    except (OSError, ValueError):
        return False


_IF_GUARD = re.compile(
    r"^if\s*\(\s*test-path\s+(?P<path>\"[^\"]*\"|'[^']*'|[^\s(){}]+)\s*\)\s*\{\s*(?P<body>[^{}]+?)\s*\}$",
    re.IGNORECASE,
)


def _output_scoped(segment: str) -> bool:
    """A file cmdlet whose every path argument is inside Output/ (fail closed).

    `if (Test-Path <p>) { <cmdlet> }` counts when <p> and the one cmdlet do.
    """
    guard = _IF_GUARD.match(segment.strip())
    if guard:
        return _in_output(guard.group("path")) and _output_scoped(guard.group("body"))
    try:
        tokens = shlex.split(segment, posix=False)
    except ValueError:
        return False
    if not tokens or tokens[0].lower() not in _OUTPUT_CMDLETS:
        return False
    shape = _OUTPUT_CMDLETS[tokens[0].lower()]
    paths: list[str] = []
    names: list[str] = []
    positional: list[str] = []
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        low = tok.lower()
        if low in _SWITCHES:
            i += 1
            continue
        if low in _PATH_PARAMS | _VALUE_PARAMS | _NAME_PARAMS:
            if i + 1 >= len(tokens):
                return False
            value = tokens[i + 1]
            if low in _PATH_PARAMS:
                paths.append(value)
            elif low in _NAME_PARAMS:
                names.append(value)
            elif "$" in value:
                return False  # content built from a variable
            elif low == "-itemtype" and value.strip("'\"").lower() in _LINK_TYPES:
                return False
            i += 2
            continue
        if tok.startswith("-"):
            return False  # a parameter this check does not know
        positional.append(tok)
        i += 1
    if shape == "paths":
        paths += positional
    elif positional:
        paths.append(positional[0])
        if shape == "path+name":
            names += positional[1:]
        elif any("$" in v for v in positional[1:]):
            return False
    if any("/" in n or "\\" in n or ".." in n or "$" in n for n in names):
        return False
    return bool(paths) and all(_in_output(p) for p in paths)


_ASSIGN = re.compile(r"^\$(\w+)\s*=\s*(.*)$", re.S)
_LITERAL = re.compile(r"""^(["'])([^"'$`]*)\1$""")


def _inline_literal_vars(segments: list[str]) -> list[str]:
    """Substitute `$name` where it is assigned once, to a plain string literal.

    The agent writes `$dir = "...\\Output\\x"; Set-Content "$dir\\a.txt" ...`.
    Without this the Output/ check saw `$dir` and failed closed. A variable
    assigned twice, or to anything but a literal free of `$` and backticks,
    is left alone, so that check still sees `$` and fails closed.
    """
    seen: dict[str, int] = {}
    literals: dict[str, str] = {}
    for segment in segments:
        m = _ASSIGN.match(segment)
        if not m:
            continue
        name = m.group(1).lower()
        seen[name] = seen.get(name, 0) + 1
        lit = _LITERAL.match(m.group(2).strip())
        if lit:
            literals[name] = lit.group(2)
    safe = {n: v for n, v in literals.items() if seen[n] == 1}
    if not safe:
        return segments

    def _inline(segment: str) -> str:
        def _sub(match: re.Match) -> str:
            value = safe.get(match.group(1).lower())
            if value is None:
                return match.group(0)
            # Bare `$dst` becomes a quoted literal, so a path with spaces
            # stays one argument; inside "..." it is spliced as is.
            inside_quotes = segment[: match.start()].count('"') % 2 == 1
            return value if inside_quotes else f'"{value}"'

        return re.sub(r"\$(\w+)\b(?!:)", _sub, segment)

    return [s if _ASSIGN.match(s) else _inline(s) for s in segments]


def split_segments(command: str) -> list[str]:
    """Split a command line on ``;`` ``&&`` ``||`` ``|`` ``&`` outside quotes.

    Pure. Returns the non-empty stripped segments; a command with no
    separator is one segment. Newlines are not separators (multi-line
    Python passed by python_execute stays one segment, as before).
    """
    segments: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(command):
        ch = command[i]
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch in ";&|":
            segments.append("".join(buf))
            buf = []
            if command[i : i + 2] in ("&&", "||"):
                i += 1
        else:
            buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return [s.strip() for s in segments if s.strip()]


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
