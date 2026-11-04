"""Approval floors: shell commands that no approval mode may wave through (H18, pure).

Every other gate can be turned off by a mode: AUTO grants every ASK. A floor cannot. A
``deny`` floor refuses the command; a ``human`` floor needs a person to say yes, even in
AUTO, and is refused when no one can answer.

A floor reads one *variant* of the command (``command_variants`` in tool_guards builds them:
the text as written, without PowerShell backticks, without quotes, and with any base64 it
carries decoded), so ``"r"m -rf ~`` and ``echo cm0gLXJmIH4= | base64 -d | sh`` meet the same
rule as ``rm -rf ~``. A floor only has to read text, never to run anything.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Literal

from weebot.core.shell_segments import split_segments

_SEGMENT = r"[^;&|\r\n]*"  # inside one command of a line


@dataclass(frozen=True)
class Floor:
    id: str
    matches: Callable[[str], bool]  # reads one variant of a command
    action: Literal["deny", "human"]
    reason: str


def _pattern(regex: str) -> Callable[[str], bool]:
    compiled = re.compile(regex, re.IGNORECASE)
    return lambda text: compiled.search(text) is not None


# ── Recursive delete of a root or a home directory ──────────────────────────

_DELETE_COMMANDS = frozenset({"rm", "rmdir", "rd", "del", "erase", "remove-item", "ri"})
_RECURSIVE_FLAG = re.compile(r"^(?:-[a-z]*r[a-z]*|--recursive|-recurse|/s)$", re.IGNORECASE)
_DRIVE_ROOT = re.compile(r"^[a-z]:$", re.IGNORECASE)
_HOME_NAMES = frozenset(
    {"~", "$home", "${home}", "$env:userprofile", "$env:home", "%userprofile%", "%homepath%"}
)


def _canonical_target(token: str) -> str:
    """``/*``, ``C:\\``, ``~/``, ``$HOME/*`` reduced to what they name."""
    stripped = token.strip().rstrip("*").rstrip("/\\")
    return (stripped or "/").lower()


def _deletes_recursively(text: str, wanted: Callable[[str], bool]) -> bool:
    for segment in split_segments(text):
        words = segment.split()
        if not words or words[0].lower() not in _DELETE_COMMANDS:
            continue
        if not any(_RECURSIVE_FLAG.match(w) for w in words[1:]):
            continue
        if any(wanted(_canonical_target(w)) for w in words[1:] if not w.startswith("-")):
            return True
    return False


def _deletes_root(text: str) -> bool:
    return _deletes_recursively(text, lambda t: t == "/" or bool(_DRIVE_ROOT.match(t)))


def _deletes_home(text: str) -> bool:
    return _deletes_recursively(text, lambda t: t in _HOME_NAMES)


# ── Writes to credential stores ─────────────────────────────────────────────

_WRITES = re.compile(
    r"(?:>|\b(?:tee|cp|mv|copy|move|set-content|add-content|out-file|new-item|rm|del|"
    r"remove-item|install|ln|dd)\b|\bsed\s+-i)",
    re.IGNORECASE,
)
# `.env.example` is not a credential file, so `.env` must end the word.
_CREDENTIAL_PATH = re.compile(
    r"(?:^|[\\/~\s])\.(?:ssh|aws|gnupg)(?:[\\/\s]|$)|(?:^|[\\/\s])\.env(?:\s|$)",
    re.IGNORECASE,
)


def _writes_credentials(text: str) -> bool:
    return any(
        _WRITES.search(segment) and _CREDENTIAL_PATH.search(segment)
        for segment in split_segments(text)
    )


# ── A forced push to the default branch ─────────────────────────────────────

_DEFAULT_BRANCH = re.compile(r"(?:^|[:/+])(?:main|master)$", re.IGNORECASE)


def _force_pushes_default_branch(text: str) -> bool:
    for segment in split_segments(text):
        words = segment.split()
        if len(words) < 3 or words[0].lower() != "git" or "push" not in words[1:3]:
            continue
        forced = any(
            w.lower().startswith(("--force", "--mirror"))
            or (w.startswith("-") and not w.startswith("--") and "f" in w)
            or w.startswith("+")  # a `+ref` refspec forces that ref
            for w in words[2:]
        )
        if forced and any(_DEFAULT_BRANCH.search(w) for w in words[2:] if not w.startswith("-")):
            return True
    return False


# ── The built-in floors ─────────────────────────────────────────────────────

BUILTIN_FLOORS: tuple[Floor, ...] = (
    Floor("delete-root", _deletes_root, "deny", "recursive delete of a filesystem or drive root"),
    Floor("delete-home", _deletes_home, "human", "recursive delete of the home directory"),
    Floor(
        "credential-write",
        _writes_credentials,
        "human",
        "writes to a credential store (.ssh, .aws, .gnupg, .env)",
    ),
    Floor(
        "force-push-default",
        _force_pushes_default_branch,
        "human",
        "force push to the default branch",
    ),
    Floor(
        "disk-format",
        _pattern(
            rf"\bmkfs(?:\.\w+)?\b|\bformat(?:\.com)?\s+[a-z]:|\bdiskpart\b"
            rf"|\b(?:fdisk|sfdisk|cfdisk|parted|gdisk|sgdisk|wipefs)\b"
            rf"|\bdd\b{_SEGMENT}\bof=/dev/|>\s*/dev/(?:sd|nvme|hd|disk)"
            rf"|\b(?:Format-Volume|Clear-Disk|Remove-Partition|Initialize-Disk|New-Partition)\b"
        ),
        "deny",
        "formats or partitions a disk",
    ),
    Floor(
        "registry-delete",
        _pattern(
            rf"\breg(?:\.exe)?\s+delete\s+[\"']?HK"
            rf"|\bRemove-Item\b{_SEGMENT}\bHK(?:LM|CU|CR|U|CC):"
        ),
        "human",
        "deletes registry keys",
    ),
    Floor(
        "download-and-run",
        _pattern(
            r"\b(?:curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod)\b[^;&\r\n|]*\|\s*"
            r"(?:sudo\s+)?(?:sh|bash|zsh|dash|ksh|iex|invoke-expression|python[\d.]*|pwsh"
            r"|powershell(?:\.exe)?)\b"
            rf"|\b(?:iex|invoke-expression)\b{_SEGMENT}"
            r"\b(?:iwr|irm|curl|wget|invoke-webrequest|invoke-restmethod|downloadstring)\b"
            rf"|\b(?:sh|bash|zsh)\b{_SEGMENT}[<$]\(\s*(?:curl|wget)\b"
        ),
        "human",
        "runs a script as it downloads",
    ),
    Floor(
        "disable-protection",
        _pattern(
            rf"\bSet-MpPreference\b{_SEGMENT}-Disable\w+\s+(?:\$true|1|true)\b"
            rf"|\bAdd-MpPreference\b{_SEGMENT}-Exclusion\w+"
            rf"|\bsc(?:\.exe)?\s+(?:stop|config)\s+(?:WinDefend|mpssvc|SecurityHealthService)\b"
            rf"|\bStop-Service\b{_SEGMENT}\b(?:WinDefend|mpssvc)\b"
            r"|\bnetsh\s+advfirewall\s+set\s+\w+\s+state\s+off\b"
            rf"|\bSet-NetFirewallProfile\b{_SEGMENT}-Enabled\s+(?:False|0|\$false)\b"
            r"|\bufw\s+disable\b"
        ),
        "human",
        "turns off Defender or the firewall",
    ),
)


def glob_floors(globs: Iterable[str]) -> tuple[Floor, ...]:
    """Deny floors from user globs (``WEEBOT_APPROVAL_DENY_GLOBS``), case-insensitive.

    A glob is tried against the whole variant and against each command in it, so
    ``npm publish*`` catches ``cd app && npm publish``.
    """
    floors = []
    for glob in globs:
        pattern = glob.strip().lower()
        if pattern:
            floors.append(
                Floor(
                    f"deny-glob:{pattern}",
                    lambda text, p=pattern: any(
                        fnmatchcase(part.lower(), p) for part in (text, *split_segments(text))
                    ),
                    "deny",
                    f"matches the deny glob '{pattern}'",
                )
            )
    return tuple(floors)


def first_floor(variants: Iterable[str], floors: Iterable[Floor]) -> Floor | None:
    """The floor *variants* meet; a ``deny`` floor wins over a ``human`` one."""
    found: Floor | None = None
    floors = tuple(floors)
    for variant in variants:
        for floor in floors:
            if floor.matches(variant):
                if floor.action == "deny":
                    return floor
                found = found or floor
    return found
