"""Assemble a :class:`Book` into a self-contained LaTeX project.

Pure functions: a ``Book`` (with authored section bodies) becomes a ``main.tex``
string plus a ``refs.bib``. The project ``\\input``s ``preamble.tex`` — the
locked preamble that the compiler materializes via ``prepare_project`` — so the
assembled tree is location-independent and safe to copy into the sandbox.
"""
from __future__ import annotations

from pathlib import Path

from weebot.domain.models.book import Book


def _escape_meta(text: str) -> str:
    """Escape the few characters that break in title/author metadata."""
    for ch in ("\\", "&", "%", "$", "#", "_", "{", "}"):
        text = text.replace(ch, "\\" + ch)
    return text


def assemble_main_tex(book: Book) -> str:
    """Render a full ``main.tex`` document for ``book``."""
    parts: list[str] = []
    parts.append("% Auto-assembled by weebot BookGenerationFlow. Do not edit by hand.")
    parts.append("\\input{preamble.tex}")
    if book.bib_entries:
        parts.append("\\addbibresource{refs.bib}")
    parts.append(f"\\title{{{_escape_meta(book.title)}}}")
    parts.append(f"\\author{{{_escape_meta(book.author)}}}")
    parts.append(f"\\date{{{book.year}}}")
    parts.append("")
    parts.append("\\begin{document}")
    parts.append("\\frontmatter")
    parts.append("\\maketitle")
    parts.append("\\tableofcontents")
    parts.append("\\mainmatter")

    for chapter in book.chapters:
        parts.append("")
        parts.append(f"\\chapter{{{chapter.title}}}")
        parts.append(f"\\label{{{chapter.label}}}")
        for section in chapter.sections:
            parts.append("")
            parts.append(f"\\section{{{section.title}}}")
            parts.append(f"\\label{{{section.label}}}")
            if section.body_tex.strip():
                parts.append(section.body_tex.rstrip())

    if book.bib_entries:
        parts.append("")
        parts.append("\\backmatter")
        parts.append("\\printbibliography")

    parts.append("\\end{document}")
    parts.append("")
    return "\n".join(parts)


def write_project(book: Book, project_dir: str | Path) -> Path:
    """Write ``main.tex`` (and ``refs.bib`` if any) into ``project_dir``.

    Assumes ``preamble.tex`` is materialized separately by the compiler's
    ``prepare_project``. Returns the path to the written ``main.tex``.
    """
    project = Path(project_dir)
    project.mkdir(parents=True, exist_ok=True)

    main_tex = project / "main.tex"
    main_tex.write_text(assemble_main_tex(book), encoding="utf-8")

    if book.bib_entries:
        (project / "refs.bib").write_text(
            "\n\n".join(e.strip() for e in book.bib_entries) + "\n", encoding="utf-8"
        )
    return main_tex
