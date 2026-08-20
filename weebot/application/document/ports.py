"""Ports (interfaces) for book generation — kept in the application layer so the
flow depends on abstractions, not on infrastructure concretes.

Concrete implementations live in ``weebot.infrastructure.document`` and are
injected at composition time (interfaces layer / tests).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from weebot.domain.models.book import Book, CompileResult


@runtime_checkable
class CompilerPort(Protocol):
    """Compiles a LaTeX project directory to a PDF, returning structured results."""

    def prepare_project(self, project_dir: str | Path) -> Path:
        """Materialize the locked preamble into ``project_dir`` as ``preamble.tex``."""
        ...

    def compile(
        self, project_dir: str | Path, main_tex: str = "main.tex", *, shell_escape: bool = False
    ) -> CompileResult: ...


@runtime_checkable
class PreflightReportLike(Protocol):
    ok: bool


@runtime_checkable
class PreflightPort(Protocol):
    """Validates a produced PDF for print-readiness."""

    def __call__(self, pdf_path: str | Path) -> PreflightReportLike: ...


@runtime_checkable
class ContentProvider(Protocol):
    """Authors body-only LaTeX for a book's sections.

    The production implementation is LLM-backed (Opus 4.8 / AUTHORING profile);
    tests use a deterministic stub. Either way it only fills section bodies —
    never the locked preamble.
    """

    def author(self, book: Book) -> Book:
        """Return a copy of ``book`` with every section's ``body_tex`` populated."""
        ...
