"""Tests for the Greek scientific-book LaTeX pipeline.

The log-parser and preflight-parser tests are pure and always run. The
end-to-end compile test is gated on the XeLaTeX toolchain being installed
(skipped otherwise), so CI without TeX Live still passes.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from weebot.application.document.book_assembler import assemble_main_tex, write_project
from weebot.application.document.book_generation_flow import BookGenerationFlow
from weebot.application.document.stub_content_provider import StubContentProvider
from weebot.domain.models.book import (
    Book,
    Chapter,
    CompileError,
    CompileErrorCategory,
    CompileResult,
    Section,
)
from weebot.infrastructure.document.latex_compiler import (
    SUPPORTED_ENGINES,
    LatexCompilerService,
)
from weebot.infrastructure.document.log_parser import has_blocking_errors, parse_log
from weebot.infrastructure.document.preflight import _parse_pdffonts, preflight_pdf


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
    not LatexCompilerService.toolchain_available(),
    reason="XeLaTeX/latexmk toolchain not installed",
)
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


# ── engine selection (pure) ─────────────────────────────────────────────────

def test_supported_engines_are_xelatex_and_lualatex():
    assert SUPPORTED_ENGINES == ("xelatex", "lualatex")


def test_compiler_rejects_unsupported_engine():
    with pytest.raises(ValueError):
        LatexCompilerService("pdflatex")


def test_with_engine_switches_and_preserves_config():
    base = LatexCompilerService("xelatex", timeout_seconds=123)
    swapped = base.with_engine("lualatex")
    assert base.engine == "xelatex"
    assert swapped.engine == "lualatex"
    assert swapped._timeout == 123  # config preserved across the switch


class _FakeCompiler:
    """A CompilerPort double: succeeds except for the named failing engines."""

    def __init__(self, engine: str = "xelatex", fail_engines=()):
        self._engine = engine
        self._fail = set(fail_engines)
        self.calls: list[str] = []

    @property
    def engine(self) -> str:
        return self._engine

    def with_engine(self, engine: str) -> "_FakeCompiler":
        sibling = _FakeCompiler(engine, self._fail)
        sibling.calls = self.calls  # share the call log across siblings
        return sibling

    def prepare_project(self, project_dir):
        Path(project_dir).mkdir(parents=True, exist_ok=True)
        return Path(project_dir) / "preamble.tex"

    def compile(self, project_dir, main_tex="main.tex", *, shell_escape=False):
        self.calls.append(self._engine)
        if self._engine in self._fail:
            return CompileResult(
                ok=False,
                engine=self._engine,
                errors=[CompileError(fatal=True, message=f"{self._engine} boom")],
            )
        return CompileResult(
            ok=True,
            engine=self._engine,
            pdf_path=str(Path(project_dir) / "main.pdf"),
            page_count=3,
        )


def _ok_preflight(_pdf_path):
    from weebot.infrastructure.document.preflight import PreflightReport
    return PreflightReport(ok=True)


def test_flow_falls_back_to_lualatex_when_xelatex_fails(tmp_path):
    fake = _FakeCompiler(fail_engines={"xelatex"})
    flow = BookGenerationFlow(
        compiler=fake,
        content_provider=StubContentProvider(),
        preflight=_ok_preflight,
    )
    result = flow.generate(_sample_book(), tmp_path / "book")

    assert result.ok
    assert result.engine == "lualatex"           # switched after XeLaTeX failed
    assert fake.calls == ["xelatex", "lualatex"]  # tried in order
    assert result.engines_tried == ["xelatex", "lualatex"]


def test_flow_stops_at_first_engine_that_succeeds(tmp_path):
    fake = _FakeCompiler(fail_engines=set())  # xelatex succeeds
    flow = BookGenerationFlow(
        compiler=fake,
        content_provider=StubContentProvider(),
        preflight=_ok_preflight,
    )
    result = flow.generate(_sample_book(), tmp_path / "book")

    assert result.ok and result.engine == "xelatex"
    assert fake.calls == ["xelatex"]  # LuaLaTeX never invoked


# ── LuaLaTeX end-to-end (needs the lualatex toolchain) ──────────────────────

@pytest.mark.slow
@pytest.mark.timeout(360)
@pytest.mark.skipif(
    not LatexCompilerService.toolchain_available("lualatex"),
    reason="LuaLaTeX/latexmk toolchain not installed",
)
def test_compile_greek_example_with_lualatex(tmp_path):
    work = tmp_path / "book"
    LatexCompilerService.prepare_project(work)
    (work / "refs.bib").write_text('@book{e,author={Euler},title={Introductio},year={1748}}\n')
    (work / "main.tex").write_text(_MINIMAL_BODY, encoding="utf-8")

    result = LatexCompilerService("lualatex").compile(work, "main.tex", shell_escape=True)

    assert result.ok, f"lualatex compile failed: {[e.message for e in result.errors]}"
    assert result.engine == "lualatex"
    assert result.pdf_path and Path(result.pdf_path).exists()
    assert not has_blocking_errors(result.errors)

    report = preflight_pdf(result.pdf_path)
    assert report.ok, f"preflight issues: {[i.message for i in report.issues]}"
    assert report.fonts_not_embedded == 0
