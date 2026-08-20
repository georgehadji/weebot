"""Parse a LaTeX (`.log`) build log into structured :class:`CompileError`s.

This is the deterministic backbone of the self-heal loop: it turns the noisy
XeLaTeX transcript into a categorized, machine-routable error list that the
escalation ladder (deterministic fixers → LLM patch → strategy switch) acts on.

The parser is engine-agnostic (works for xelatex/lualatex/pdflatex logs) and
pure — it takes log text and returns models, with no file or process I/O.
"""

from __future__ import annotations

import re

from weebot.domain.models.book import CompileError, CompileErrorCategory

# --- regexes over the LaTeX transcript -------------------------------------
_RE_FATAL = re.compile(r"^! (.+)$")
_RE_MISSING_PACKAGE = re.compile(r"File `([^']+\.sty)' not found|! LaTeX Error: File `([^']+)'")
_RE_UNDEF_CS = re.compile(r"^! Undefined control sequence")
_RE_MISSING_GLYPH = re.compile(
    r"Missing character: There is no (.+?) \((U\+[0-9A-Fa-f]+)\) in font (.+?):"
)
_RE_UNDEF_REF = re.compile(r"Reference [`']([^']+)' on page \d+ undefined")
_RE_UNDEF_CITE = re.compile(r"Citation '([^']+)' on page \d+ undefined")
_RE_OVERFULL = re.compile(r"Overfull \\hbox \(([\d.]+)pt too wide\)")
_RE_FILELINE = re.compile(r"^(.+?):(\d+): (.+)$")  # -file-line-error style
_RE_BIBLATEX = re.compile(r"Package biblatex (Warning|Error): (.+)")
_RE_MINTED = re.compile(
    r"you must invoke (?:LaTeX|latex) with the -shell-escape flag|Package minted Error"
)


def _categorize_fatal(message: str) -> CompileErrorCategory:
    m = message.lower()
    if "undefined control sequence" in m:
        return CompileErrorCategory.UNDEFINED_CONTROL_SEQUENCE
    if "file" in m and "not found" in m:
        return CompileErrorCategory.MISSING_PACKAGE
    if "shell-escape" in m or "minted" in m:
        return CompileErrorCategory.MINTED_SHELL_ESCAPE
    if "biblatex" in m or "biber" in m:
        return CompileErrorCategory.BIBLIOGRAPHY
    if "missing" in m and ("$" in message or "math" in m):
        return CompileErrorCategory.SYNTAX
    return CompileErrorCategory.SYNTAX


def parse_log(log_text: str) -> list[CompileError]:
    """Return the structured errors/warnings found in a LaTeX build log."""
    errors: list[CompileError] = []
    seen: set[str] = set()

    def add(err: CompileError) -> None:
        if err.signature not in seen:
            seen.add(err.signature)
            errors.append(err)

    lines = log_text.splitlines()
    for i, line in enumerate(lines):
        # Fatal "! ..." errors — grab the next non-empty line as extra context.
        m = _RE_FATAL.match(line)
        if m:
            msg = m.group(1).strip()
            add(CompileError(category=_categorize_fatal(msg), message=msg, fatal=True))
            continue

        for gm in _RE_MISSING_GLYPH.finditer(line):
            add(
                CompileError(
                    category=CompileErrorCategory.MISSING_GLYPH,
                    message=f"No glyph {gm.group(1)} ({gm.group(2)}) in font {gm.group(3)}",
                )
            )

        rm = _RE_UNDEF_REF.search(line)
        if rm:
            add(
                CompileError(
                    category=CompileErrorCategory.UNDEFINED_REFERENCE,
                    message=f"Undefined reference '{rm.group(1)}'",
                )
            )

        cm = _RE_UNDEF_CITE.search(line)
        if cm:
            add(
                CompileError(
                    category=CompileErrorCategory.UNDEFINED_CITATION,
                    message=f"Undefined citation '{cm.group(1)}'",
                )
            )

        om = _RE_OVERFULL.search(line)
        if om:
            add(
                CompileError(
                    category=CompileErrorCategory.OVERFULL_BOX,
                    message=f"Overfull hbox {om.group(1)}pt too wide",
                )
            )

        bm = _RE_BIBLATEX.search(line)
        if bm and bm.group(1) == "Error":
            add(
                CompileError(
                    category=CompileErrorCategory.BIBLIOGRAPHY,
                    message=f"biblatex: {bm.group(2)}",
                    fatal=True,
                )
            )

        if _RE_MINTED.search(line):
            add(
                CompileError(
                    category=CompileErrorCategory.MINTED_SHELL_ESCAPE,
                    message="minted requires -shell-escape (sandbox-only)",
                    fatal=True,
                )
            )

    return errors


def has_blocking_errors(errors: list[CompileError]) -> bool:
    """True if any error must be resolved before the PDF can be considered done."""
    blocking = {
        CompileErrorCategory.UNDEFINED_REFERENCE,
        CompileErrorCategory.UNDEFINED_CITATION,
        CompileErrorCategory.MISSING_GLYPH,
    }
    return any(e.fatal or e.category in blocking for e in errors)
