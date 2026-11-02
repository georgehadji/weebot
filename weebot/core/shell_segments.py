"""Split a command into the segments the approval policy judges one by one (pure).

A shell runs each command between ``;`` ``&&`` ``||`` ``|`` ``&`` and each line as its own
command, so all of those separate segments outside quotes (audit 2026-10-29 R01: a newline
used to be no separator, and a delete on the line after an auto-approved Output\\ write ran
unasked). Python code passed by python_execute is one block: its lines are not commands.

No line-continuation joining: PowerShell's backtick and bash's backslash would let
``dir C:\\`` + newline glue the next command onto a read. A continued command is judged as
separate lines instead, which can only ask more often.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, replace
from enum import Enum

_BACKTICK_NOT_BEFORE_NEWLINE = re.compile(r"`(?![\r\n])")
# A command name that is not a literal word: `& ("Invoke-" + "Expression")`, `& $cmd`, `. (...)`.
_DYNAMIC_NAME = re.compile(
    r"""(?:^|[;|&{(\r\n])[ \t]*[&.][ \t]*(?:\(|\$|["'][^"'\r\n]*["'][ \t]*\+)""", re.M
)
# `Set-Variable`, `New-Variable` and the `-Variable` family write a variable by name.
_VARIABLE_BY_NAME = re.compile(
    r"\b(?:set|new|clear|remove)-variable\b|-(?:out|error|warning|information|pipeline)?variable\b"
    r"|-[oewip]v\b|\[ref\]",
    re.I,
)


def strip_escapes(text: str) -> str:
    """PowerShell drops a backtick inside a word: ``Invoke-Ex`pression`` is Invoke-Expression.

    A backtick before a newline joins lines and is kept, so no two words are glued together.
    """
    return _BACKTICK_NOT_BEFORE_NEWLINE.sub("", text)


def has_dynamic_command_name(text: str) -> bool:
    """True when a command's name is built at run time, so no rule can read it."""
    return _DYNAMIC_NAME.search(text) is not None


@dataclass(frozen=True)
class ShellWord:
    """One word of a segment, with what PowerShell would do to it before using it.

    A word with any flag set is not what its text says: a policy that matches the text
    must treat it as unknown (ask), never as the path it looks like.
    """

    text: str
    has_escape: bool = False  # a backtick: ``Output/.`./x`` is ``Output/../x``
    has_variable: bool = False  # `$x` expands to anything
    # `*` or `?` in a directory part, or any `[`: it can walk through a junction a literal path
    # would not. A `*` in the last part only picks files (`Output/tmp/*.tmp`) and is allowed.
    has_wildcard: bool = False
    is_list: bool = False  # `a,b` is two items
    is_unc: bool = False  # `\\host\share` opens a network connection
    is_dynamic_name: bool = False  # the command name is built by the shell

    @property
    def is_plain(self) -> bool:
        return not (
            self.has_escape or self.has_variable or self.has_wildcard or self.is_list
            or self.is_unc or self.is_dynamic_name
        )


def parse_word(text: str) -> ShellWord:
    """Parse, do not validate: the flags are read once here, not re-derived by each caller."""
    bare = text.strip("'\"")
    directories, _, leaf = bare.replace("\\", "/").rpartition("/")
    return ShellWord(
        text=text,
        has_escape="`" in text,
        has_variable="$" in text or "~" in text,
        has_wildcard=any(c in directories for c in "*?[]") or any(c in leaf for c in "[]"),
        is_list="," in text or ";" in text,
        is_unc=bare.startswith(("\\\\", "//")),
    )


def tokenize(segment: str) -> list[ShellWord]:
    """The words of one segment; empty when its quotes do not balance (fail closed)."""
    try:
        raw = shlex.split(segment, posix=False)
    except ValueError:
        return []
    words = [parse_word(t) for t in raw]
    if words and has_dynamic_command_name(segment):
        words[0] = replace(words[0], is_dynamic_name=True)
    return words


# A segment that moves the shell: what follows it no longer runs in this workspace.
_DIR_CHANGERS = frozenset({
    "cd", "chdir", "sl", "set-location", "push-location", "pushd", "pop-location", "popd",
})


def changes_directory(segment: str) -> bool:
    first = segment.strip().split(None, 1)
    return bool(first) and first[0].strip("&.\"'").lower() in _DIR_CHANGERS


def after_directory_change(segments: list[str]) -> list[bool]:
    """For each segment: does a directory change come before it in the chain?

    The conservative rule; real working-directory tracking is not worth the complexity.
    """
    moved = False
    flags: list[bool] = []
    for segment in segments:
        flags.append(moved)
        moved = moved or changes_directory(segment)
    return flags


class SegmentSyntax(Enum):
    SHELL = "shell"
    PYTHON = "python"


def split_segments(command: str, *, syntax: SegmentSyntax = SegmentSyntax.SHELL) -> list[str]:
    """The non-empty stripped segments of *command*, split outside quotes.

    SHELL splits on ``;`` ``&&`` ``||`` ``|`` ``&`` and on ``\\n`` / ``\\r``; PYTHON splits on
    the same operators but keeps newlines inside its segment, as before.
    """
    separators = ";&|\r\n" if syntax is SegmentSyntax.SHELL else ";&|"
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
        elif ch in separators:
            segments.append("".join(buf))
            buf = []
            if command[i : i + 2] in ("&&", "||"):
                i += 1
        else:
            buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return [s.strip() for s in segments if s.strip()]


_ASSIGN = re.compile(r"^\$(\w+)\s*=\s*(.*)$", re.S)
_LITERAL = re.compile(r"""^(["'])([^"'$`]*)\1$""")


def inline_literal_vars(segments: list[str]) -> list[str]:
    """Substitute `$name` where it is assigned once, to a plain string literal.

    The agent writes `$dir = "...\\Output\\x"; Set-Content "$dir\\a.txt" ...`.
    Without this the Output/ check saw `$dir` and failed closed. A variable
    assigned twice, or to anything but a literal free of `$` and backticks,
    is left alone, so that check still sees `$` and fails closed.

    "Assigned" means any write, not only `=`: `+=`, `-=`, `++`, a write inside `{ }` or an
    `if`, `[ref]`, `Set-Variable`. Each is counted by name over the whole command, so a form
    this function does not list cannot hide a second assignment.
    """
    joined = "\n".join(segments)
    if _VARIABLE_BY_NAME.search(joined):
        return segments  # a variable written by name: nothing here is safe to inline
    literals: dict[str, str] = {}
    for segment in segments:
        m = _ASSIGN.match(segment)
        lit = _LITERAL.match(m.group(2).strip()) if m else None
        if m and lit:
            literals[m.group(1).lower()] = lit.group(2)
    safe = {
        n: v
        for n, v in literals.items()
        if len(re.findall(rf"\${re.escape(n)}\b\s*(?:[-+*/%]?=(?!=)|\+\+|--)", joined, re.I)) == 1
    }
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
