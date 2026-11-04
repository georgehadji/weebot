"""One finding from a language server: where it is, how bad, and what it says."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnostic:
    path: str
    line: int  # 0-based start of the range, as LSP sends it
    column: int
    end_line: int
    end_column: int
    severity: str  # error | warning | info | hint
    code: str
    message: str
    source: str
