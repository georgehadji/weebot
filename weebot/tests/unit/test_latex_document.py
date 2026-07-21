"""Tests for the Greek scientific-book LaTeX pipeline.

The log-parser and preflight-parser tests are pure and always run. The
end-to-end compile test is gated on the XeLaTeX toolchain being installed
(skipped otherwise), so CI without TeX Live still passes.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from weebot.domain.models.book import CompileErrorCategory
from weebot.infrastructure.document.latex_compiler import LatexCompilerService
from weebot.infrastructure.document.log_parser import has_blocking_errors, parse_log
from weebot.infrastructure.document.preflight import _parse_pdffonts, preflight_pdf


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


@pytest.mark.skipif(
    not LatexCompilerService.toolchain_available(),
    reason="XeLaTeX/latexmk toolchain not installed",
)
def test_compile_greek_example_end_to_end(tmp_path):
    work = tmp_path / "book"
    LatexCompilerService.prepare_project(work)
    (work / "refs.bib").write_text('@book{e,author={Euler},title={Introductio},year={1748}}\n')
    (work / "main.tex").write_text(_MINIMAL_BODY, encoding="utf-8")

    result = LatexCompilerService().compile(work, "main.tex", shell_escape=True)

    assert result.ok, f"compile failed: {[e.message for e in result.errors]}"
    assert result.pdf_path and Path(result.pdf_path).exists()
    assert result.page_count and result.page_count >= 1
    assert not has_blocking_errors(result.errors)

    report = preflight_pdf(result.pdf_path)
    assert report.ok, f"preflight issues: {[i.message for i in report.issues]}"
    assert report.fonts_not_embedded == 0
