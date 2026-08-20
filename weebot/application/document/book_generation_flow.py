"""BookGenerationFlow — orchestrates spec → PDF with a self-healing compile loop.

Pipeline (see tasks/scientific-book-latex-plan.md, Phases 1–6):

    author content → assemble project → compile → (self-heal loop) → preflight

The self-heal loop is the escalation ladder's control structure: after each
compile, blocking errors are routed to an injected ``fixer`` (Rung 0 deterministic
fixers / Rung 1 LLM patch). A **no-progress detector** compares error signatures
between iterations — an unchanged signature set forces the loop to stop rather
than retry the same fix forever. LLM authoring and fixers are injected ports, so
this flow is fully testable without live model calls.
"""

from __future__ import annotations

import logging
from pathlib import Path
from collections.abc import Callable

from pydantic import BaseModel, Field

from weebot.application.document.book_assembler import write_project
from weebot.application.document.ports import CompilerPort, ContentProvider, PreflightPort
from weebot.domain.models.book import Book, CompileError, CompileResult

logger = logging.getLogger(__name__)

# A fixer receives the current blocking errors and the project dir; it applies
# edits in place and returns True if it changed anything (Rung 0 / Rung 1).
Fixer = Callable[[list[CompileError], Path], bool]


def _null_fixer(_errors: list[CompileError], _project: Path) -> bool:
    """Default: make no changes (loop relies on latexmk's own multi-pass)."""
    return False


class GenerationResult(BaseModel):
    ok: bool = Field(default=False)
    pdf_path: str | None = Field(default=None)
    page_count: int | None = Field(default=None)
    iterations: int = Field(default=0)
    preflight_ok: bool = Field(default=False)
    preflight_issues: list[str] = Field(default_factory=list)
    remaining_errors: list[CompileError] = Field(default_factory=list)

    @property
    def print_ready(self) -> bool:
        return self.ok and self.preflight_ok


class BookGenerationFlow:
    """Turn a :class:`Book` spec into a print-ready PDF."""

    def __init__(
        self,
        compiler: CompilerPort,
        content_provider: ContentProvider,
        preflight: PreflightPort,
        *,
        fixer: Fixer = _null_fixer,
        max_iterations: int = 5,
        shell_escape: bool = True,
    ) -> None:
        self._compiler = compiler
        self._content = content_provider
        self._preflight = preflight
        self._fixer = fixer
        self._max_iterations = max_iterations
        self._shell_escape = shell_escape

    @staticmethod
    def _signatures(errors: list[CompileError]) -> frozenset[str]:
        return frozenset(e.signature for e in errors if e.fatal or _is_blocking(e))

    def generate(self, book: Book, output_dir: str | Path) -> GenerationResult:
        project = Path(output_dir)

        # Phase 1–2: author section bodies, then assemble the project.
        authored = self._content.author(book)
        self._compiler.prepare_project(project)
        write_project(authored, project)

        # Phase 5: compile + self-heal loop with no-progress detection.
        result: CompileResult = CompileResult()
        last_sig: frozenset[str] | None = None
        iterations = 0

        for iterations in range(1, self._max_iterations + 1):
            result = self._compiler.compile(project, "main.tex", shell_escape=self._shell_escape)
            blocking = [e for e in result.errors if e.fatal or _is_blocking(e)]
            if result.ok and not blocking:
                break

            sig = self._signatures(result.errors)
            if sig == last_sig:
                logger.warning("book-gen: no progress (identical error signatures) — stopping loop")
                break
            last_sig = sig

            changed = self._fixer(blocking, project)
            if not changed:
                # Nothing left to try deterministically; surface to caller.
                logger.info("book-gen: fixer made no changes — stopping loop")
                break

        # Phase 6: print-readiness preflight (only meaningful if a PDF exists).
        preflight_ok = False
        issues: list[str] = []
        if result.pdf_path:
            report = self._preflight(result.pdf_path)
            preflight_ok = bool(report.ok)
            issues = [getattr(i, "message", str(i)) for i in getattr(report, "issues", [])]

        remaining = [e for e in result.errors if e.fatal or _is_blocking(e)]
        return GenerationResult(
            ok=result.ok,
            pdf_path=result.pdf_path,
            page_count=result.page_count,
            iterations=iterations,
            preflight_ok=preflight_ok,
            preflight_issues=issues,
            remaining_errors=remaining,
        )


def _is_blocking(error: CompileError) -> bool:
    from weebot.domain.models.book import CompileErrorCategory

    return error.category in {
        CompileErrorCategory.UNDEFINED_REFERENCE,
        CompileErrorCategory.UNDEFINED_CITATION,
        CompileErrorCategory.MISSING_GLYPH,
    }
