# Greek scientific book — proof of concept

A minimal, verified end-to-end example of a Greek scientific book compiled by
weebot's LaTeX pipeline. Demonstrates **math** (Euler's identity, the Basel
problem), a **table** of constants, a native **pgfplots figure** (binary
entropy), a **minted code listing with Greek comments**, and a **biblatex
bibliography** — all cross-referenced with Greek `\cref` names.

## Build

Requires the XeLaTeX toolchain (see `tasks/scientific-book-latex-plan.md`,
Phase 0): `texlive-xetex`, `texlive-lang-greek`, `latexmk`, `biber`,
`python3-pygments`, and the GFS Greek fonts.

```bash
latexmk -xelatex -shell-escape -interaction=nonstopmode main.tex
```

`-shell-escape` is required by `minted`; in production this runs **only inside
the sandbox** (`weebot/infrastructure/sandbox/`).

## What it proves

A clean run yields a 9-page PDF with **0 LaTeX errors, 0 missing-glyph
warnings, all cross-references and citations resolved, and every font
embedded** — the correctness + print-readiness gates from the plan.

The locked preamble it `\input`s lives at
`weebot/infrastructure/document/templates/greek_scientific_preamble.tex`.
Its load order is deliberate and documented in the file header (hyperref /
bookmark / cleveref before polyglossia; biblatex after polyglossia; a
Greek-capable sans font for KOMA headings).
