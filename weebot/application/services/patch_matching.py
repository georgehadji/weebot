"""Find where an edit goes, tolerating the small errors a model makes copying text (H6).

``apply_patch(text, old, new)`` tries an ordered chain of pure strategies, strictest
first. The first strategy that finds the text decides: exactly one place applies the
edit, several places refuse it (listing the lines), and none at all falls through to
the next strategy. Nothing here touches the filesystem.
"""

from __future__ import annotations

import difflib
import re
import textwrap
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

Rewrite = Callable[[str], str]


@dataclass(frozen=True)
class Span:
    """``text[start:end]`` is what the edit replaces; ``rewrite`` adapts the new text to it."""

    start: int
    end: int
    rewrite: Rewrite | None = None

    def __eq__(self, other: object) -> bool:  # a callable has no useful equality
        return isinstance(other, Span) and (self.start, self.end) == (other.start, other.end)

    def __hash__(self) -> int:
        return hash((self.start, self.end))


class MatchStrategy(Protocol):
    name: str

    def find(self, haystack: str, needle: str) -> list[Span]: ...


@dataclass(frozen=True)
class PatchOutcome:
    ok: bool
    text: str = ""  # the patched text, when ok
    strategy: str = ""  # which strategy placed the edit, when ok
    line: int = 0  # 1-based line where the edit starts, when ok
    error: str = ""


# ── helpers ─────────────────────────────────────────────────────────────────


def _lines(text: str) -> list[tuple[int, int, str]]:
    """``(start, end, content)`` per line, ``end`` before the line terminator."""
    out, pos = [], 0
    for raw in text.splitlines(keepends=True):
        content = raw.rstrip("\r\n")
        out.append((pos, pos + len(content), content))
        pos += len(raw)
    return out


def _windows(haystack: str, needle: str):
    """Every run of haystack lines as long as the needle: ``(start, end, lines)``."""
    want = len(needle.splitlines())
    lines = _lines(haystack)
    for i in range(len(lines) - want + 1):
        run = lines[i : i + want]
        yield run[0][0], run[-1][1], [r[2] for r in run]


def _all_occurrences(haystack: str, needle: str) -> list[int]:
    found, pos = [], haystack.find(needle)
    while pos != -1:
        found.append(pos)
        pos = haystack.find(needle, pos + 1)
    return found


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _reindenter(old_indent: str, new_indent: str) -> Rewrite:
    """Move the replacement from the indentation the model used to the file's."""

    def rewrite(new: str) -> str:
        return "\n".join(
            new_indent + ln[len(old_indent) :] if ln.strip() and ln.startswith(old_indent) else ln
            for ln in new.split("\n")
        )

    return rewrite


def _normalized(text: str, char_fn: Callable[[str], str], collapse_ws: bool):
    """``text`` mapped char by char; returns it with each char's original ``(start, end)``."""
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        if collapse_ws and text[i].isspace():
            j = i
            while j < len(text) and text[j].isspace():
                j += 1
            out.append(" ")
            spans.append((i, j))
            i = j
            continue
        mapped = char_fn(text[i])
        out.extend(mapped)
        spans.extend([(i, i + 1)] * len(mapped))
        i += 1
    return "".join(out), spans


def _find_normalized(
    haystack: str, needle: str, char_fn: Callable[[str], str], collapse_ws: bool
) -> list[Span]:
    norm_hay, spans = _normalized(haystack, char_fn, collapse_ws)
    norm_needle, _ = _normalized(needle, char_fn, collapse_ws)
    norm_needle = norm_needle.strip() if collapse_ws else norm_needle
    if not norm_needle:
        return []
    return [
        Span(spans[p][0], spans[p + len(norm_needle) - 1][1])
        for p in _all_occurrences(norm_hay, norm_needle)
    ]


# ── strategies ──────────────────────────────────────────────────────────────


class Exact:
    name = "exact"

    def find(self, haystack: str, needle: str) -> list[Span]:
        return [Span(p, p + len(needle)) for p in _all_occurrences(haystack, needle)]


class LineTrimmed:
    """Lines equal once leading and trailing blanks are stripped."""

    name = "line_trimmed"

    def find(self, haystack: str, needle: str) -> list[Span]:
        want = [ln.strip() for ln in needle.splitlines()]
        found = []
        for start, end, run in _windows(haystack, needle):
            if [ln.strip() for ln in run] == want:
                rewrite = _reindenter(_indent(needle.splitlines()[0]), _indent(run[0]))
                found.append(Span(start, end, rewrite))
        return found


class WhitespaceNormalized:
    """Equal once every run of whitespace counts as one space."""

    name = "whitespace_normalized"

    def find(self, haystack: str, needle: str) -> list[Span]:
        return _find_normalized(haystack, needle, lambda c: c, collapse_ws=True)


class IndentationFlexible:
    """Equal once the common indentation is removed from both."""

    name = "indentation_flexible"

    def find(self, haystack: str, needle: str) -> list[Span]:
        want = textwrap.dedent(needle).splitlines()
        found = []
        for start, end, run in _windows(haystack, needle):
            if textwrap.dedent("\n".join(run)).splitlines() == want:
                rewrite = _reindenter(_indent(needle.splitlines()[0]), _indent(run[0]))
                found.append(Span(start, end, rewrite))
        return found


_ESCAPES = {"\\n": "\n", "\\t": "\t", '\\"': '"', "\\'": "'", "\\\\": "\\"}
_ESCAPE_RE = re.compile("|".join(re.escape(k) for k in _ESCAPES))


def _unescape(text: str) -> str:
    return _ESCAPE_RE.sub(lambda m: _ESCAPES[m.group(0)], text)


class EscapeNormalized:
    """The model wrote ``\\n`` or ``\\"`` as two characters where the file has one."""

    name = "escape_normalized"

    def find(self, haystack: str, needle: str) -> list[Span]:
        plain = _unescape(needle)
        if plain == needle:
            return []
        return [Span(p, p + len(plain), _unescape) for p in _all_occurrences(haystack, plain)]


_TYPOGRAPHY = str.maketrans(
    {
        "‘": "'", "’": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", "−": "-", " ": " ",
    }
)  # fmt: skip


def _fold(char: str) -> str:
    return unicodedata.normalize("NFKC", char.translate(_TYPOGRAPHY))


class UnicodeNormalized:
    """Equal once smart quotes and dashes are plain and the text is NFKC."""

    name = "unicode_normalized"

    def find(self, haystack: str, needle: str) -> list[Span]:
        return _find_normalized(haystack, needle, _fold, collapse_ws=False)


class BlockAnchor:
    """Same first and last line; the lines between are at least ``min_ratio`` alike."""

    name = "block_anchor"

    def __init__(self, min_ratio: float = 0.8) -> None:
        self._min_ratio = min_ratio

    def find(self, haystack: str, needle: str) -> list[Span]:
        wanted = needle.splitlines()
        if len(wanted) < 3:
            return []
        first, last = wanted[0].strip(), wanted[-1].strip()
        middle = "\n".join(ln.strip() for ln in wanted[1:-1])
        found = []
        for start, end, run in _windows(haystack, needle):
            if run[0].strip() != first or run[-1].strip() != last:
                continue
            seen = "\n".join(ln.strip() for ln in run[1:-1])
            if difflib.SequenceMatcher(None, seen, middle).ratio() >= self._min_ratio:
                rewrite = _reindenter(_indent(wanted[0]), _indent(run[0]))
                found.append(Span(start, end, rewrite))
        return found


STRATEGIES: tuple[MatchStrategy, ...] = (
    Exact(),
    LineTrimmed(),
    WhitespaceNormalized(),
    IndentationFlexible(),
    EscapeNormalized(),
    UnicodeNormalized(),
    BlockAnchor(min_ratio=0.8),
)


# ── the chain ───────────────────────────────────────────────────────────────


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _closest(text: str, old: str) -> str:
    """The text nearest to ``old``, for the error message (or '' when nothing is close)."""
    wanted = [ln.strip() for ln in old.splitlines() if ln.strip()]
    if not wanted:
        return ""
    lines = text.splitlines()
    stripped = [ln.strip() for ln in lines]
    near = difflib.get_close_matches(wanted[0], stripped, n=1, cutoff=0.6)
    if not near:
        return ""
    at = stripped.index(near[0])
    snippet = "\n".join(lines[at : at + min(len(old.splitlines()), 10)])
    return f"Closest text is at line {at + 1}:\n{snippet[:600]}"


def _trim_tail(old: str, new: str) -> tuple[str, str]:
    tail = old[len(old.rstrip("\r\n")) :]
    if not tail:
        return old, new
    return old[: -len(tail)], new[: -len(tail)] if new.endswith(tail) else new


def apply_patch(
    text: str,
    old: str,
    new: str,
    *,
    strategies: tuple[MatchStrategy, ...] = STRATEGIES,
) -> PatchOutcome:
    """Replace ``old`` with ``new`` at the one place the first matching strategy finds."""
    if not old:
        return PatchOutcome(ok=False, error="old_str must not be empty.")
    original_old, original_new = old, new
    for strategy in strategies:
        # Line-based strategies end a span before the line break, so drop the break from both.
        old, new = (
            (original_old, original_new)
            if strategy.name == "exact"
            else _trim_tail(original_old, original_new)
        )
        spans = strategy.find(text, old)
        if not spans:
            continue
        if len(spans) > 1:
            lines = ", ".join(str(_line_of(text, s.start)) for s in spans[:8])
            return PatchOutcome(
                ok=False,
                error=(
                    f"old_str matches {len(spans)} places (lines {lines}) by {strategy.name}. "
                    "Add surrounding lines to make it unique."
                ),
            )
        span = spans[0]
        replacement = span.rewrite(new) if span.rewrite else new
        return PatchOutcome(
            ok=True,
            text=text[: span.start] + replacement + text[span.end :],
            strategy=strategy.name,
            line=_line_of(text, span.start),
        )
    hint = _closest(text, old)
    return PatchOutcome(ok=False, error="old_str not found." + (f" {hint}" if hint else ""))
