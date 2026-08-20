"""Tests for the Greek scientific-book LaTeX pipeline.

The log-parser and preflight-parser tests are pure and always run. The
end-to-end compile test is gated on the XeLaTeX toolchain being installed
(skipped otherwise), so CI without TeX Live still passes.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from weebot.application.document.book_assembler import assemble_main_tex, write_project
from weebot.application.document.book_generation_flow import BookGenerationFlow
from weebot.application.document.stub_content_provider import StubContentProvider
from weebot.core.bash_guard import RiskLevel
from weebot.domain.models.book import Book, Chapter, CompileErrorCategory, Section
from weebot.infrastructure.document.latex_compiler import LatexCompilerService
from weebot.infrastructure.document.log_parser import has_blocking_errors, parse_log
from weebot.infrastructure.document.preflight import _parse_pdffonts, preflight_pdf

# Computed once at collection time so both toolchain-gated tests below share
# the same fc-list probe rather than shelling out twice each.
_MISSING_FONTS = LatexCompilerService.missing_fonts()


def _sample_book() -> Book:
    return Book(
        title="Δοκιμαστικό Βιβλίο",
        author="weebot",
        chapters=[
            Chapter(
                label="chap:intro",
                title="Εισαγωγή",
                sections=[Section(label="sec:one", title="Πρώτη Ενότητα")],
            )
        ],
        bib_entries=["@book{e,author={Euler},title={Introductio},year={1748}}"],
    )


# ── log parser ─────────────────────────────────────────────────────────────


def test_parse_undefined_reference_and_citation():
    log = (
        "LaTeX Warning: Reference `eq:euler' on page 1 undefined on input line 34.\n"
        "LaTeX Warning: Citation 'euler1748' on page 1 undefined on input line 23.\n"
    )
    errors = parse_log(log)
    cats = {e.category for e in errors}
    assert CompileErrorCategory.UNDEFINED_REFERENCE in cats
    assert CompileErrorCategory.UNDEFINED_CITATION in cats
    assert has_blocking_errors(errors)


def test_parse_missing_glyph():
    log = "Missing character: There is no π (U+03C0) in font [lmsans10-bold]:mapping=tex-t\n"
    errors = parse_log(log)
    assert errors and errors[0].category == CompileErrorCategory.MISSING_GLYPH
    assert has_blocking_errors(errors)


def test_parse_fatal_undefined_control_sequence():
    errors = parse_log("! Undefined control sequence.\n")
    assert errors[0].fatal
    assert errors[0].category == CompileErrorCategory.UNDEFINED_CONTROL_SEQUENCE


def test_parse_biblatex_ordering_error():
    log = "! Package biblatex Error: 'polyglossia' loaded after biblatex.\n"
    errors = parse_log(log)
    assert any(e.category == CompileErrorCategory.BIBLIOGRAPHY and e.fatal for e in errors)


def test_clean_log_has_no_blocking_errors():
    assert not has_blocking_errors(parse_log("This is a normal log line.\n"))


def test_error_signature_dedupes():
    log = "! Undefined control sequence.\n! Undefined control sequence.\n"
    assert len(parse_log(log)) == 1


# ── preflight parser ────────────────────────────────────────────────────────


def test_parse_pdffonts_detects_not_embedded():
    out = (
        "name              type    encoding  emb sub uni object ID\n"
        "----              ----    --------  --- --- --- ---------\n"
        "ABCDEF+GFSDidot   CID     Identity  yes yes yes  10 0\n"
        "Helvetica         Type1   WinAnsi   no  no  no   11 0\n"
    )
    total, not_embedded = _parse_pdffonts(out)
    assert total == 2
    assert not_embedded == 1


# ── end-to-end compile (needs XeLaTeX) ──────────────────────────────────────

_MINIMAL_BODY = r"""\input{preamble.tex}
\addbibresource{refs.bib}
\begin{document}
\frontmatter\tableofcontents
\mainmatter
\chapter{Εισαγωγή}\label{chap:intro}
\section{Μαθηματικά}\label{sec:math}
Η \cref{eq:euler} και ο \cref{tab:c}. Πηγή \autocite{e}.
\begin{equation}e^{i\pi}+1=0.\label{eq:euler}\end{equation}
\begin{table}[htbp]\centering\caption{Σταθερές}\label{tab:c}
\begin{tabular}{@{}lc@{}}\toprule Σταθερά & Τιμή \\ \midrule Πι & $3{,}14$ \\ \bottomrule\end{tabular}
\end{table}
\begin{listing}[htbp]
\begin{minted}{python}
def f(x):
    # Ελληνικό σχόλιο
    return x
\end{minted}
\caption{Κώδικας}\label{lst:f}
\end{listing}
\backmatter\printbibliography
\end{document}
"""


# ── assembly (pure) ─────────────────────────────────────────────────────────


def test_assemble_main_tex_structure():
    tex = assemble_main_tex(_sample_book())
    assert "\\input{preamble.tex}" in tex
    assert "\\frontmatter" in tex and "\\mainmatter" in tex
    assert "\\chapter{Εισαγωγή}" in tex and "\\label{chap:intro}" in tex
    assert "\\section{Πρώτη Ενότητα}" in tex
    assert "\\addbibresource{refs.bib}" in tex and "\\printbibliography" in tex


def test_stub_content_provider_fills_empty_bodies():
    authored = StubContentProvider().author(_sample_book())
    body = authored.chapters[0].sections[0].body_tex
    assert body.strip() and "$" in body  # non-empty, contains math


def test_write_project_emits_files(tmp_path):
    write_project(StubContentProvider().author(_sample_book()), tmp_path)
    assert (tmp_path / "main.tex").exists()
    assert (tmp_path / "refs.bib").exists()
    assert "Euler" in (tmp_path / "refs.bib").read_text()


@pytest.mark.timeout(15)
def test_compile_timeout_returns_result_instead_of_hanging(tmp_path, monkeypatch):
    """Finding G: a slow compile must return a TIMEOUT CompileResult, not hang.

    Regresses the bug where killing only the direct child (latexmk) left an
    orphaned grandchild (xelatex) holding the stdout/stderr pipes open, so
    the post-kill drain blocked forever. Simulates that exact shape: a
    wrapper process spawns a child that outlives it. Hangs on the
    pre-fix subprocess.run(timeout=) implementation — the @pytest.mark.timeout
    is a backstop, not the thing under test.
    """
    service = LatexCompilerService(timeout_seconds=1)
    monkeypatch.setattr(service._guard, "evaluate", lambda cmd: (RiskLevel.SAFE, "test"))
    orphaning_wrapper = (
        "import subprocess, sys; "
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], close_fds=False); "
        "p.wait()"
    )
    monkeypatch.setattr(
        service,
        "_build_command",
        lambda main_tex, shell_escape: [sys.executable, "-c", orphaning_wrapper],
    )

    started = time.monotonic()
    result = service.compile(tmp_path, "main.tex")
    elapsed = time.monotonic() - started

    assert elapsed < 10, f"compile() must return shortly after its own timeout, took {elapsed:.1f}s"
    assert not result.ok
    assert any(e.category == CompileErrorCategory.TIMEOUT for e in result.errors)


# ── end-to-end flow (needs XeLaTeX) ─────────────────────────────────────────


@pytest.mark.slow
# LatexCompilerService budgets 300s per compile, but the suite-wide pytest
# timeout is 60s — so on a machine that actually has the toolchain (CI skips
# via skipif) this drove an opaque pytest kill mid-subprocess instead of a
# CompileResult. Exceed the compiler budget so its own timeout wins and the
# assertion below reports a real error list. First MiKTeX run is slow: it
# fetches packages on demand.
@pytest.mark.timeout(360)
@pytest.mark.skipif(
    not LatexCompilerService.toolchain_available(), reason="XeLaTeX/latexmk toolchain not installed"
)
@pytest.mark.skipif(bool(_MISSING_FONTS), reason=f"missing fonts: {_MISSING_FONTS}")
def test_generation_flow_produces_print_ready_pdf(tmp_path):
    flow = BookGenerationFlow(
        compiler=LatexCompilerService(),
        content_provider=StubContentProvider(),
        preflight=preflight_pdf,
    )
    result = flow.generate(_sample_book(), tmp_path / "book")

    assert result.ok, f"remaining: {[e.message for e in result.remaining_errors]}"
    assert result.print_ready
    assert result.page_count and result.page_count >= 1
    assert result.pdf_path and Path(result.pdf_path).exists()


@pytest.mark.slow
@pytest.mark.timeout(360)  # see the note on the previous test
@pytest.mark.skipif(
    not LatexCompilerService.toolchain_available(), reason="XeLaTeX/latexmk toolchain not installed"
)
@pytest.mark.skipif(bool(_MISSING_FONTS), reason=f"missing fonts: {_MISSING_FONTS}")
def test_compile_greek_example_end_to_end(tmp_path):
    work = tmp_path / "book"
    LatexCompilerService.prepare_project(work)
    (work / "refs.bib").write_text("@book{e,author={Euler},title={Introductio},year={1748}}\n")
    (work / "main.tex").write_text(_MINIMAL_BODY, encoding="utf-8")

    result = LatexCompilerService().compile(work, "main.tex", shell_escape=True)

    assert result.ok, f"compile failed: {[e.message for e in result.errors]}"
    assert result.pdf_path and Path(result.pdf_path).exists()
    assert result.page_count and result.page_count >= 1
    assert not has_blocking_errors(result.errors)

    report = preflight_pdf(result.pdf_path)
    assert report.ok, f"preflight issues: {[i.message for i in report.issues]}"
    assert report.fonts_not_embedded == 0
