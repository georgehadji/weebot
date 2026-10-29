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
from enum import Enum


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
