"""Domain models for LaTeX scientific-book generation.

Pure domain layer: no I/O, no framework coupling. These models describe a
Greek (or other-language) scientific book, the assets it contains, and the
structured result of compiling it to a print-ready PDF.

See tasks/scientific-book-latex-plan.md for the full design.
"""

from __future__ import annotations

from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class AssetKind(str, Enum):
    """The kinds of embeddable content a chapter body can reference."""

    EQUATION = "equation"
    TABLE = "table"
    FIGURE = "figure"
    LISTING = "listing"


class BookAsset(BaseModel):
    """A labelled, cross-referenceable element inside a chapter."""

    kind: AssetKind
    label: str = Field(description="LaTeX label, e.g. 'fig:entropy'")
    caption: str = Field(default="")


class Section(BaseModel):
    label: str = Field(description="LaTeX label, e.g. 'sec:equations'")
    title: str
    body_tex: str = Field(default="", description="Body-only LaTeX (no preamble)")
    assets: list[BookAsset] = Field(default_factory=list)


class Chapter(BaseModel):
    label: str = Field(description="LaTeX label, e.g. 'chap:analysis'")
    title: str
    sections: list[Section] = Field(default_factory=list)


class Book(BaseModel):
    """A complete scientific book specification and its assembled content."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    author: str = Field(default="weebot")
    language: str = Field(default="el", description="ISO 639-1, e.g. 'el' for Greek")
    year: int = Field(default=2026)
    chapters: list[Chapter] = Field(default_factory=list)
    bib_entries: list[str] = Field(
        default_factory=list, description="Raw BibTeX entry strings for refs.bib"
    )


class CompileErrorCategory(str, Enum):
    """Error taxonomy that drives the self-heal escalation ladder."""

    MISSING_PACKAGE = "missing_package"
    UNDEFINED_CONTROL_SEQUENCE = "undefined_control_sequence"
    SYNTAX = "syntax"
    UNDEFINED_REFERENCE = "undefined_reference"
    UNDEFINED_CITATION = "undefined_citation"
    MISSING_GLYPH = "missing_glyph"
    BIBLIOGRAPHY = "bibliography"
    FLOAT_PLACEMENT = "float_placement"
    OVERFULL_BOX = "overfull_box"
    IMAGE = "image"
    MINTED_SHELL_ESCAPE = "minted_shell_escape"
    ENCODING = "encoding"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class CompileError(BaseModel):
    """A single structured issue extracted from a LaTeX build log."""

    category: CompileErrorCategory = CompileErrorCategory.UNKNOWN
    message: str = Field(default="")
    file: str | None = Field(default=None)
    line: int | None = Field(default=None)
    fatal: bool = Field(default=False, description="True for '! ...' errors that abort the run")

    @property
    def signature(self) -> str:
        """Stable identity used by the no-progress detector."""
        return f"{self.category.value}|{self.file}|{self.line}|{self.message[:80]}"


class CompileResult(BaseModel):
    """Outcome of one compilation pass."""

    ok: bool = Field(default=False)
    pdf_path: str | None = Field(default=None)
    page_count: int | None = Field(default=None)
    errors: list[CompileError] = Field(default_factory=list)
    log_tail: str = Field(default="", description="Last lines of the build log")

    @property
    def fatal_errors(self) -> list[CompileError]:
        return [e for e in self.errors if e.fatal]
